"""Agent Service - autonomous task execution with planning and feedback loops.

This service enables the assistant to work like OpenClaw:
- Break down complex tasks into steps
- Execute steps autonomously with feedback loops
- Handle failures with retries
- Continue running while user is away
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from typing import Any, Callable, Coroutine, Optional

from koda2.logging_config import get_logger
from koda2.modules.agent.models import AgentStatus, AgentStep, AgentTask, StepStatus
from koda2.modules.llm.models import ChatMessage, LLMRequest

logger = get_logger(__name__)

# Prompt for creating an execution plan
PLANNING_PROMPT = """You are a task planning agent. Your job is to break down a user request into a concrete, executable plan.

The user wants: {request}

Available tools/actions you can use:
- run_shell: Execute shell commands (ls, cat, find, grep, mkdir, cd, git, npm, python, etc.)
- write_file: Create or overwrite files
- read_file: Read file contents
- list_directory: List directory contents
- send_whatsapp: Send WhatsApp message
- send_email: Send email
- generate_document: Create DOCX, XLSX, PDF, PPTX
- generate_image: Generate images with AI
- check_calendar: Check calendar events
- search_memory: Search conversation history
- file_exists: Check if file exists
- And all other commands from the command registry

Create a step-by-step plan. Each step should:
1. Have a clear description of what it does
2. Use one specific action
3. Be verifiable (you can check if it succeeded)
4. Build on previous steps

IMPORTANT: 
- Use FULL FILE PATHS (e.g., /Users/username/project/file.txt)
- For shell commands, be explicit about working directory
- If you need to create a directory first, make that a separate step
- Break complex tasks into small, testable steps

Respond in JSON format:
{{
    "plan": [
        {{
            "id": "step_1",
            "description": "Create project directory",
            "action": {{"action": "run_shell", "params": {{"command": "mkdir -p /Users/username/my_project"}}}}
        }},
        {{
            "id": "step_2", 
            "description": "Initialize git repository",
            "action": {{"action": "run_shell", "params": {{"command": "git init", "cwd": "/Users/username/my_project"}}}}
        }}
    ],
    "estimated_steps": 2,
    "estimated_duration": "5 minutes"
}}

If the request is unclear or you need more information, respond with:
{{
    "needs_clarification": true,
    "questions": ["What should be the project name?", "Which programming language?"]
}}
"""

# Prompt for handling step execution results
REFLECTION_PROMPT = """You are executing a multi-step task. Review the result and decide what to do next.

Original request: {original_request}

Current plan progress:
{progress_summary}

Last step executed:
- Step: {step_description}
- Action: {action}
- Result: {result}
- Status: {status}

Overall context so far:
{context}

Decide what to do next:
1. If the step succeeded: proceed to next step
2. If the step failed but is retryable: suggest a fix and retry
3. If the step failed permanently: suggest an alternative approach
4. If we need user input: ask for clarification

Respond in JSON format:
{{
    "decision": "continue|retry|alternative|ask_user|complete",
    "reasoning": "Brief explanation of decision",
    "next_action": {{"action": "action_name", "params": {{...}}}},  // Only if alternative
    "questions": ["Question for user?"]  // Only if ask_user
}}
"""


class AgentService:
    """Service for autonomous agent task execution."""
    
    def __init__(
        self,
        llm_router: Any,
        orchestrator: Any,
    ):
        self.llm = llm_router
        self.orch = orchestrator
        self._tasks: dict[str, AgentTask] = {}
        self._running: set[asyncio.Task] = set()
        self._shutdown = False
        self._callbacks: list[Callable[[AgentTask], Coroutine[Any, Any, None]]] = []
        
    def register_callback(
        self,
        callback: Callable[[AgentTask], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback for task status updates."""
        self._callbacks.append(callback)
    
    async def _notify_callbacks(self, task: AgentTask) -> None:
        """Notify all callbacks of task update."""
        for callback in self._callbacks:
            try:
                await callback(task)
            except Exception as exc:
                logger.error("agent_callback_failed", error=str(exc))
    
    async def create_task(
        self,
        user_id: str,
        request: str,
        auto_start: bool = True,
    ) -> AgentTask:
        """Create a new agent task from a user request.
        
        This will:
        1. Use LLM to create an execution plan
        2. Store the task
        3. Optionally start execution immediately
        """
        task_id = str(uuid.uuid4())
        task = AgentTask(
            id=task_id,
            user_id=user_id,
            original_request=request,
            status=AgentStatus.PLANNING,
        )
        self._tasks[task_id] = task
        
        logger.info("agent_task_created", task_id=task_id, request=request[:100])
        
        # Generate plan using LLM
        try:
            plan = await self._generate_plan(task)
            if plan is None:
                # Need clarification
                task.status = AgentStatus.WAITING
                await self._notify_callbacks(task)
                return task
            
            task.plan = plan
            task.status = AgentStatus.PENDING
            logger.info("agent_plan_created", task_id=task_id, steps=len(plan))
            
        except Exception as exc:
            logger.error("agent_planning_failed", task_id=task_id, error=str(exc))
            task.status = AgentStatus.FAILED
            task.error_message = f"Failed to create plan: {exc}"
            await self._notify_callbacks(task)
            return task
        
        await self._notify_callbacks(task)
        
        if auto_start:
            await self.start_task(task_id)
        
        return task
    
    async def _generate_plan(self, task: AgentTask) -> Optional[list[AgentStep]]:
        """Generate an execution plan using LLM."""
        prompt = PLANNING_PROMPT.format(request=task.original_request)
        
        request = LLMRequest(
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=0.3,
        )
        
        response = await self.llm.complete(request)
        content = response.content
        
        # Extract JSON from response
        try:
            # Try to find JSON block
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            data = json.loads(content.strip())
            
            # Check if needs clarification
            if data.get("needs_clarification"):
                task.context["clarification_questions"] = data.get("questions", [])
                return None
            
            # Parse plan steps
            steps = []
            for step_data in data.get("plan", []):
                step = AgentStep(
                    id=step_data.get("id", f"step_{len(steps)+1}"),
                    description=step_data.get("description", ""),
                    action=step_data.get("action", {}),
                )
                steps.append(step)
            
            return steps
            
        except json.JSONDecodeError as exc:
            logger.error("agent_plan_json_parse_failed", content=content[:500], error=str(exc))
            raise ValueError(f"Could not parse plan: {exc}")
    
    async def start_task(self, task_id: str) -> AgentTask:
        """Start executing a task."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        if task.status not in (AgentStatus.PENDING, AgentStatus.PAUSED):
            raise ValueError(f"Cannot start task in status: {task.status}")
        
        task.status = AgentStatus.RUNNING
        task.started_at = dt.datetime.now(dt.UTC)
        
        logger.info("agent_task_started", task_id=task_id)
        await self._notify_callbacks(task)
        
        # Start execution in background
        exec_task = asyncio.create_task(self._execute_task(task_id))
        self._running.add(exec_task)
        exec_task.add_done_callback(self._running.discard)
        
        return task
    
    async def _execute_task(self, task_id: str) -> None:
        """Execute a task plan step by step."""
        task = self._tasks.get(task_id)
        if not task:
            return
        
        try:
            while task.current_step_index < len(task.plan):
                if self._shutdown:
                    logger.info("agent_shutdown_pausing", task_id=task_id)
                    task.status = AgentStatus.PAUSED
                    await self._notify_callbacks(task)
                    return
                
                step = task.plan[task.current_step_index]
                logger.info("agent_step_start", task_id=task_id, step=step.id, description=step.description)
                
                # Execute the step
                success = await self._execute_step(task, step)
                
                if success:
                    task.current_step_index += 1
                    await self._notify_callbacks(task)
                else:
                    # Step failed - use LLM to decide what to do
                    should_continue = await self._handle_step_failure(task, step)
                    if not should_continue:
                        return
                
                # Small delay between steps to prevent overwhelming systems
                await asyncio.sleep(0.5)
            
            # All steps completed
            task.status = AgentStatus.COMPLETED
            task.completed_at = dt.datetime.now(dt.UTC)
            task.result_summary = await self._generate_summary(task)
            logger.info("agent_task_completed", task_id=task_id)
            await self._notify_callbacks(task)
            
        except Exception as exc:
            logger.error("agent_task_failed", task_id=task_id, error=str(exc))
            task.status = AgentStatus.FAILED
            task.error_message = str(exc)
            await self._notify_callbacks(task)
    
    async def _execute_step(self, task: AgentTask, step: AgentStep) -> bool:
        """Execute a single step and return success status."""
        step.status = StepStatus.RUNNING
        step.started_at = dt.datetime.now(dt.UTC)
        await self._notify_callbacks(task)
        
        try:
            # Execute the action through the orchestrator
            action_name = step.action.get("action", "")
            params = step.action.get("params", {})
            
            logger.debug("agent_executing_action", task_id=task.id, step=step.id, action=action_name)
            
            result = await self.orch._execute_action(
                user_id=task.user_id,
                action=step.action,
                entities={},  # Entities would be extracted if needed
            )
            
            step.result = result
            step.status = StepStatus.COMPLETED
            step.completed_at = dt.datetime.now(dt.UTC)
            
            # Store result in context for future steps
            task.context[f"result_{step.id}"] = result
            
            logger.info("agent_step_completed", task_id=task.id, step=step.id)
            await self._notify_callbacks(task)
            return True
            
        except Exception as exc:
            step.error = str(exc)
            step.status = StepStatus.FAILED
            step.retry_count += 1
            
            logger.error("agent_step_failed", task_id=task.id, step=step.id, error=str(exc), retry=step.retry_count)
            await self._notify_callbacks(task)
            return False
    
    async def _handle_step_failure(self, task: AgentTask, step: AgentStep) -> bool:
        """Handle a failed step using LLM reflection. Returns True to continue, False to stop."""
        
        # If max retries exceeded, try to replan
        if step.retry_count >= step.max_retries:
            logger.warning("agent_max_retries_exceeded", task_id=task.id, step=step.id)
            
            # Use LLM to decide what to do
            progress = self._format_progress(task)
            
            prompt = REFLECTION_PROMPT.format(
                original_request=task.original_request,
                progress_summary=progress,
                step_description=step.description,
                action=json.dumps(step.action),
                result=json.dumps(step.result) if step.result else "None",
                status="failed",
                context=json.dumps(task.context, default=str),
            )
            
            request = LLMRequest(
                messages=[ChatMessage(role="user", content=prompt)],
                temperature=0.3,
            )
            
            try:
                response = await self.llm.complete(request)
                content = response.content
                
                # Extract JSON
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                decision = json.loads(content.strip())
                decision_type = decision.get("decision", "ask_user")
                
                if decision_type == "retry":
                    # Reset step and try again
                    step.status = StepStatus.PENDING
                    step.retry_count = 0
                    logger.info("agent_decision_retry", task_id=task.id, step=step.id)
                    return True
                    
                elif decision_type == "alternative":
                    # Replace current step with alternative
                    step.action = decision.get("next_action", step.action)
                    step.status = StepStatus.PENDING
                    step.retry_count = 0
                    logger.info("agent_decision_alternative", task_id=task.id, step=step.id)
                    return True
                    
                elif decision_type == "ask_user":
                    task.status = AgentStatus.WAITING
                    task.context["waiting_for"] = {
                        "step": step.id,
                        "questions": decision.get("questions", ["What should I do?"]),
                    }
                    logger.info("agent_decision_ask_user", task_id=task.id, step=step.id)
                    await self._notify_callbacks(task)
                    return False
                    
                elif decision_type == "complete":
                    # Mark as completed with partial success
                    task.status = AgentStatus.COMPLETED
                    task.result_summary = f"Completed with partial success. Failed at: {step.description}"
                    task.completed_at = dt.datetime.now(dt.UTC)
                    logger.info("agent_decision_complete_partial", task_id=task.id)
                    await self._notify_callbacks(task)
                    return False
                    
            except Exception as exc:
                logger.error("agent_reflection_failed", task_id=task.id, error=str(exc))
                task.status = AgentStatus.FAILED
                task.error_message = f"Step failed after {step.retry_count} retries and reflection failed: {exc}"
                await self._notify_callbacks(task)
                return False
        
        # Retry the step
        step.status = StepStatus.PENDING
        return True
    
    def _format_progress(self, task: AgentTask) -> str:
        """Format task progress for LLM prompt."""
        lines = [f"Step {task.current_step_index + 1} of {len(task.plan)}"]
        for i, step in enumerate(task.plan):
            status = "✓" if step.status == StepStatus.COMPLETED else "○"
            if i == task.current_step_index:
                status = "→"
            lines.append(f"  {status} {step.description}")
        return "\n".join(lines)
    
    async def _generate_summary(self, task: AgentTask) -> str:
        """Generate a summary of the completed task."""
        completed_steps = sum(1 for s in task.plan if s.status == StepStatus.COMPLETED)
        return f"Completed {completed_steps}/{len(task.plan)} steps"
    
    async def provide_clarification(
        self,
        task_id: str,
        answers: dict[str, str],
    ) -> AgentTask:
        """Provide user clarification for a waiting task."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        if task.status != AgentStatus.WAITING:
            raise ValueError(f"Task is not waiting for clarification: {task.status}")
        
        # Update context with answers
        task.context["clarification_answers"] = answers
        task.status = AgentStatus.RUNNING
        
        logger.info("agent_clarification_provided", task_id=task_id)
        await self._notify_callbacks(task)
        
        # Continue execution
        exec_task = asyncio.create_task(self._execute_task(task_id))
        self._running.add(exec_task)
        exec_task.add_done_callback(self._running.discard)
        
        return task
    
    async def cancel_task(self, task_id: str) -> AgentTask:
        """Cancel a running or pending task."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        task.status = AgentStatus.CANCELLED
        task.completed_at = dt.datetime.now(dt.UTC)
        
        logger.info("agent_task_cancelled", task_id=task_id)
        await self._notify_callbacks(task)
        return task
    
    async def pause_task(self, task_id: str) -> AgentTask:
        """Pause a running task."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        if task.status != AgentStatus.RUNNING:
            raise ValueError(f"Cannot pause task in status: {task.status}")
        
        task.status = AgentStatus.PAUSED
        logger.info("agent_task_paused", task_id=task_id)
        await self._notify_callbacks(task)
        return task
    
    async def resume_task(self, task_id: str) -> AgentTask:
        """Resume a paused task."""
        return await self.start_task(task_id)
    
    async def get_task(self, task_id: str) -> Optional[AgentTask]:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    async def list_tasks(
        self,
        user_id: Optional[str] = None,
        status: Optional[AgentStatus] = None,
        limit: int = 50,
    ) -> list[AgentTask]:
        """List tasks with optional filtering."""
        tasks = list(self._tasks.values())
        
        if user_id:
            tasks = [t for t in tasks if t.user_id == user_id]
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        # Sort by created_at desc
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]
    
    async def shutdown(self) -> None:
        """Gracefully shutdown the agent service."""
        self._shutdown = True
        
        # Cancel all running tasks
        for task in self._running:
            task.cancel()
        
        if self._running:
            await asyncio.gather(*self._running, return_exceptions=True)
        
        logger.info("agent_service_shutdown")

"""Agent Service - autonomous task execution using the native tool-calling loop.

This service enables the assistant to work autonomously in the background:
- Uses the same LLM tool-calling loop as process_message
- Runs as a background asyncio task with higher iteration limits
- Handles failures with LLM reflection
- Notifies user when complete (even if they're away)
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

# Higher limits for background agent tasks
AGENT_MAX_ITERATIONS = 50
AGENT_RESULT_TRUNCATE = 8000

AGENT_SYSTEM_PROMPT = """You are Koda2 Agent, an autonomous task executor running in the background.

You have tools available to take real actions. Execute the user's request step by step.
Use tools to accomplish the task — don't just describe what you would do.

RULES:
1. ALWAYS use tools to fulfill the request. Never just say "I'll do that".
2. Work through the task methodically — check results, handle errors, adapt.
3. If a tool fails, try an alternative approach.
4. When the task is fully complete, respond with a clear summary of what was done.
5. Be thorough — verify your work (e.g., check files exist after creating them).
6. For shell commands: use full paths, check exit codes.
7. If you truly cannot proceed, explain why clearly."""


class AgentService:
    """Service for autonomous agent task execution using native tool-calling."""
    
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
        """Create and optionally start a background agent task.
        
        Uses the same tool-calling loop as process_message but runs
        in the background with higher iteration limits.
        """
        task_id = str(uuid.uuid4())
        task = AgentTask(
            id=task_id,
            user_id=user_id,
            original_request=request,
            status=AgentStatus.PENDING,
        )
        self._tasks[task_id] = task
        
        logger.info("agent_task_created", task_id=task_id, request=request[:100])
        await self._notify_callbacks(task)
        
        if auto_start:
            await self.start_task(task_id)
        
        return task
    
    async def start_task(self, task_id: str) -> AgentTask:
        """Start executing a task in the background."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        if task.status not in (AgentStatus.PENDING, AgentStatus.PAUSED):
            raise ValueError(f"Cannot start task in status: {task.status}")
        
        task.status = AgentStatus.RUNNING
        task.started_at = dt.datetime.now(dt.UTC)
        
        logger.info("agent_task_started", task_id=task_id)
        await self._notify_callbacks(task)
        
        # Start the tool-calling loop in background
        exec_task = asyncio.create_task(self._run_tool_loop(task))
        self._running.add(exec_task)
        exec_task.add_done_callback(self._running.discard)
        
        return task
    
    async def _run_tool_loop(self, task: AgentTask) -> None:
        """Run the native tool-calling agent loop for a background task.
        
        This is the same pattern as orchestrator.process_message but:
        - Runs in background (asyncio.Task)
        - Higher iteration limit (AGENT_MAX_ITERATIONS)
        - Tracks steps as AgentStep objects for progress reporting
        - Notifies user on completion/failure
        """
        try:
            # Get tool definitions from orchestrator's command registry
            tools = self.orch.commands.to_openai_tools()
            
            now = dt.datetime.now()
            system = AGENT_SYSTEM_PROMPT + (
                f"\n\nCurrent date/time: {now.strftime('%A %d %B %Y, %H:%M')} (Europe/Amsterdam)"
            )
            
            messages: list[ChatMessage] = [
                ChatMessage(role="user", content=task.original_request),
            ]
            
            iteration = 0
            total_tokens = 0
            
            while iteration < AGENT_MAX_ITERATIONS:
                if self._shutdown:
                    task.status = AgentStatus.PAUSED
                    logger.info("agent_shutdown_pausing", task_id=task.id)
                    await self._notify_callbacks(task)
                    return
                
                iteration += 1
                
                # Don't pass tools on last iteration to force a text response
                request = LLMRequest(
                    messages=messages,
                    system_prompt=system,
                    temperature=0.3,
                    tools=tools if iteration < AGENT_MAX_ITERATIONS else None,
                )
                
                try:
                    llm_response = await self.llm.complete(request)
                except Exception as exc:
                    logger.error("agent_llm_failed", task_id=task.id, error=str(exc))
                    task.status = AgentStatus.FAILED
                    task.error_message = f"LLM call failed: {exc}"
                    await self._notify_callbacks(task)
                    return
                
                total_tokens += llm_response.total_tokens
                task.context["total_tokens"] = total_tokens
                task.context["iterations"] = iteration
                
                # No tool calls → LLM is done
                if not llm_response.tool_calls:
                    task.status = AgentStatus.COMPLETED
                    task.completed_at = dt.datetime.now(dt.UTC)
                    task.result_summary = llm_response.content or "Task completed."
                    logger.info("agent_task_completed", task_id=task.id, iterations=iteration, tokens=total_tokens)
                    await self._notify_callbacks(task)
                    return
                
                # LLM wants to call tools
                logger.info(
                    "agent_tool_calls",
                    task_id=task.id,
                    iteration=iteration,
                    tools=[tc["function"]["name"] for tc in llm_response.tool_calls],
                )
                
                # Add assistant message with tool_calls to history
                messages.append(ChatMessage(
                    role="assistant",
                    content=llm_response.content or "",
                    tool_calls=llm_response.tool_calls,
                ))
                
                # Execute each tool call
                for tc in llm_response.tool_calls:
                    func_name = tc["function"]["name"]
                    try:
                        args_str = tc["function"]["arguments"]
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    
                    # Track as an AgentStep for progress reporting
                    step = AgentStep(
                        id=f"iter{iteration}_{func_name}",
                        description=f"{func_name}({json.dumps(args, default=str)[:100]})",
                        action={"action": func_name, "params": args},
                        status=StepStatus.RUNNING,
                        started_at=dt.datetime.now(dt.UTC),
                    )
                    task.plan.append(step)
                    
                    try:
                        result = await self.orch._execute_action(
                            user_id=task.user_id,
                            action={"action": func_name, "params": args},
                            entities={},
                        )
                        result_str = json.dumps(result, default=str, ensure_ascii=False)
                        if len(result_str) > AGENT_RESULT_TRUNCATE:
                            result_str = result_str[:AGENT_RESULT_TRUNCATE] + "... (truncated)"
                        
                        step.status = StepStatus.COMPLETED
                        step.completed_at = dt.datetime.now(dt.UTC)
                        step.result = result
                        
                    except Exception as exc:
                        result_str = json.dumps({"error": str(exc)}, ensure_ascii=False)
                        step.status = StepStatus.FAILED
                        step.error = str(exc)
                        step.completed_at = dt.datetime.now(dt.UTC)
                        logger.error("agent_tool_failed", task_id=task.id, tool=func_name, error=str(exc))
                    
                    # Add tool result to conversation
                    messages.append(ChatMessage(
                        role="tool",
                        content=result_str,
                        tool_call_id=tc["id"],
                    ))
                
                await self._notify_callbacks(task)
                
                # Small delay between iterations
                await asyncio.sleep(0.3)
            
            # Hit max iterations
            task.status = AgentStatus.COMPLETED
            task.completed_at = dt.datetime.now(dt.UTC)
            task.result_summary = f"Reached max iterations ({AGENT_MAX_ITERATIONS}). Partial completion."
            logger.warning("agent_max_iterations", task_id=task.id)
            await self._notify_callbacks(task)
            
        except Exception as exc:
            logger.error("agent_task_failed", task_id=task.id, error=str(exc))
            task.status = AgentStatus.FAILED
            task.error_message = str(exc)
            task.completed_at = dt.datetime.now(dt.UTC)
            await self._notify_callbacks(task)
    
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
        
        task.context["clarification_answers"] = answers
        task.status = AgentStatus.RUNNING
        
        logger.info("agent_clarification_provided", task_id=task_id)
        await self._notify_callbacks(task)
        
        # Restart the loop with clarification context
        exec_task = asyncio.create_task(self._run_tool_loop(task))
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
        
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]
    
    async def shutdown(self) -> None:
        """Gracefully shutdown the agent service."""
        self._shutdown = True
        
        for task in self._running:
            task.cancel()
        
        if self._running:
            await asyncio.gather(*self._running, return_exceptions=True)
        
        logger.info("agent_service_shutdown")

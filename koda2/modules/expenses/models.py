"""Expense data models."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ExpenseStatus(StrEnum):
    """Expense status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REIMBURSED = "reimbursed"


class ExpenseCategory(StrEnum):
    """Expense categories."""
    TRAVEL = "travel"
    ACCOMMODATION = "accommodation"
    MEALS = "meals"
    TRANSPORT = "transport"
    OFFICE_SUPPLIES = "office_supplies"
    ENTERTAINMENT = "entertainment"
    TRAINING = "training"
    COMMUNICATION = "communication"
    OTHER = "other"


class Expense(BaseModel):
    """Individual expense item."""
    id: str = Field(default_factory=lambda: str(id(dt.datetime.now())))
    
    # Basic info
    date: dt.date
    description: str
    category: ExpenseCategory
    amount: Decimal
    currency: str = "EUR"
    vat_amount: Optional[Decimal] = None
    vat_percentage: Optional[Decimal] = None
    
    # Merchant info
    merchant_name: Optional[str] = None
    merchant_address: Optional[str] = None
    merchant_kvk: Optional[str] = None  # Dutch Chamber of Commerce number
    merchant_vat: Optional[str] = None  # VAT/BTW number
    
    # Receipt
    receipt_image_path: Optional[str] = None
    receipt_extracted_text: Optional[str] = None
    
    # Metadata
    project_code: Optional[str] = None
    cost_center: Optional[str] = None
    notes: str = ""
    status: ExpenseStatus = ExpenseStatus.PENDING
    
    # Audit
    submitted_by: str
    submitted_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    approved_by: Optional[str] = None
    approved_at: Optional[dt.datetime] = None
    
    @field_validator("amount", "vat_amount", mode="before")
    @classmethod
    def validate_decimal(cls, v):
        if v is None:
            return None
        return Decimal(str(v))
        
    def calculate_vat(self) -> Decimal:
        """Calculate VAT amount if percentage is known."""
        if self.vat_percentage and not self.vat_amount:
            return self.amount * (self.vat_percentage / Decimal("100"))
        return self.vat_amount or Decimal("0")
        
    def approve(self, approver: str) -> None:
        """Approve the expense."""
        self.status = ExpenseStatus.APPROVED
        self.approved_by = approver
        self.approved_at = dt.datetime.now(dt.UTC)
        
    def reject(self) -> None:
        """Reject the expense."""
        self.status = ExpenseStatus.REJECTED
        
    def reimburse(self) -> None:
        """Mark as reimbursed."""
        self.status = ExpenseStatus.REIMBURSED


class ExpenseReport(BaseModel):
    """Expense report containing multiple expenses."""
    id: str = Field(default_factory=lambda: str(id(dt.datetime.now())))
    title: str
    description: str = ""
    employee_name: str
    employee_id: Optional[str] = None
    department: Optional[str] = None
    
    # Period
    period_start: dt.date
    period_end: dt.date
    
    # Expenses
    expenses: list[Expense] = Field(default_factory=list)
    
    # Totals (computed)
    @property
    def total_amount(self) -> Decimal:
        return sum((e.amount for e in self.expenses), Decimal("0"))
        
    @property
    def total_vat(self) -> Decimal:
        return sum((e.calculate_vat() for e in self.expenses), Decimal("0"))
        
    @property
    def total_reclaimable(self) -> Decimal:
        return self.total_amount - self.total_vat
        
    # Status
    status: ExpenseStatus = ExpenseStatus.PENDING
    submitted_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    approved_at: Optional[dt.datetime] = None
    
    # Files
    pdf_path: Optional[str] = None
    excel_path: Optional[str] = None
    
    def add_expense(self, expense: Expense) -> None:
        """Add an expense to the report."""
        self.expenses.append(expense)
        
    def get_expenses_by_category(self) -> dict[ExpenseCategory, list[Expense]]:
        """Group expenses by category."""
        result: dict[ExpenseCategory, list[Expense]] = {}
        for expense in self.expenses:
            if expense.category not in result:
                result[expense.category] = []
            result[expense.category].append(expense)
        return result
        
    def get_category_totals(self) -> dict[ExpenseCategory, Decimal]:
        """Get total amount per category."""
        totals: dict[ExpenseCategory, Decimal] = {}
        for expense in self.expenses:
            if expense.category not in totals:
                totals[expense.category] = Decimal("0")
            totals[expense.category] += expense.amount
        return totals

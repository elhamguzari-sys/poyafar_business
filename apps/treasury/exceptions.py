# apps/treasury/exceptions.py




class InsufficientTreasuryBalance(Exception):
    """موجودی خزانه کافی نیست."""
    def __init__(self, message, current_balance=None, required_amount=None, currency='AFG'):
        super().__init__(message)
        self.message = message
        self.current_balance = current_balance
        self.required_amount = required_amount
        self.currency = currency


class TreasuryReversalBlocked(Exception):
    """برگشت تراکنش باعث منفی شدن خزانه می‌شود."""
    def __init__(self, message, transaction=None, current_balance=None, would_become=None, currency='AFG'):
        super().__init__(message)
        self.message = message
        self.transaction = transaction
        self.current_balance = current_balance
        self.would_become = would_become
        self.currency = currency
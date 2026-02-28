#!/usr/bin/env python3
"""
SEC Financial Statements Parser
Extracts income statement, balance sheet, and cash flow from SEC filings.
"""

import requests
from typing import Dict, Any, Optional
from datetime import datetime

from sec_utils import get_cik_from_ticker


class SECFinancialsClient:
    """Client for retrieving financial statements from SEC filings."""

    BASE_URL = "https://data.sec.gov"
    COMPANY_FACTS_URL = f"{BASE_URL}/api/xbrl/companyfacts"

    def __init__(self):
        self.headers = {
            'User-Agent': 'SEC-MCP CLI maxforgan@google.com'
        }

    def get_company_facts(self, cik: str) -> Dict:
        """Get all company facts (financial data) for a CIK."""
        url = f"{self.COMPANY_FACTS_URL}/CIK{cik}.json"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise Exception(f"Error fetching company facts: {e}")

    def _period_days(self, v: dict) -> Optional[int]:
        """Return the number of days covered by a filing period."""
        start, end = v.get('start'), v.get('end')
        if not start or not end:
            return None
        try:
            return (datetime.strptime(end, '%Y-%m-%d') - datetime.strptime(start, '%Y-%m-%d')).days
        except Exception:
            return None

    def _filter_flow_values(self, values: list, periods: int) -> list:
        """
        Filter income/cash flow values to include:
        - 10-K annual periods (~365 days)
        - 10-Q single-quarter periods (~90 days), excluding year-to-date cumulative entries
        Deduplicates by (end date, form type) and returns most recent `periods` entries.
        """
        filtered = []
        for v in values:
            form = v.get('form', '')
            days = self._period_days(v)
            if days is None:
                continue
            if form == '10-K' and 340 <= days <= 380:
                filtered.append(v)
            elif form == '10-Q' and 60 <= days <= 100:
                filtered.append(v)

        # Deduplicate by (end, form) keeping the most recently filed version
        seen: Dict[tuple, dict] = {}
        for v in sorted(filtered, key=lambda x: x.get('filed', ''), reverse=True):
            key = (v.get('end'), v.get('form'))
            if key not in seen:
                seen[key] = v

        return sorted(seen.values(), key=lambda x: x.get('end', ''), reverse=True)[:periods]

    def _filter_balance_values(self, values: list, periods: int) -> list:
        """
        Filter balance sheet values (point-in-time) from 10-K and 10-Q.
        Deduplicates by end date, keeping the most recently filed version.
        """
        filtered = [v for v in values if v.get('form') in ('10-K', '10-Q')]

        seen: Dict[str, dict] = {}
        for v in sorted(filtered, key=lambda x: x.get('filed', ''), reverse=True):
            end = v.get('end', '')
            if end not in seen:
                seen[end] = v

        return sorted(seen.values(), key=lambda x: x.get('end', ''), reverse=True)[:periods]

    def _get_first_matching(self, us_gaap: dict, gaap_keys: list, filter_fn, periods: int) -> list:
        """Try each GAAP tag in order and return data from the first one that has values."""
        for gaap_key in gaap_keys:
            if gaap_key not in us_gaap:
                continue
            units = us_gaap[gaap_key].get('units', {})
            if 'USD' in units:
                values = units['USD']
            elif 'USD/shares' in units:
                values = units['USD/shares']
            elif 'shares' in units:
                values = units['shares']
            else:
                continue
            result = filter_fn(values, periods)
            if result:
                return result
        return []

    def get_income_statement(self, ticker: str, periods: int = 4) -> Dict[str, Any]:
        """
        Get income statement for a ticker.

        Args:
            ticker: Stock ticker symbol
            periods: Number of periods to retrieve (default: 4); includes both annual
                     (10-K) and single-quarter (10-Q) periods, sorted most recent first.
        """
        try:
            cik = get_cik_from_ticker(ticker, self.headers)
            facts = self.get_company_facts(cik)
            us_gaap = facts.get('facts', {}).get('us-gaap', {})

            income_statement = {
                'ticker': ticker.upper(),
                'cik': cik,
                'statement': 'Income Statement',
                'data': {}
            }

            # Each entry: display_name -> [gaap_tags...] tried in priority order
            line_items = {
                'Revenues': [
                    'Revenues',
                    'RevenueFromContractWithCustomerExcludingAssessedTax',
                    'RevenueFromContractWithCustomerIncludingAssessedTax',
                    'SalesRevenueNet',
                    'SalesRevenueGoodsNet',
                ],
                'Cost of Revenue': [
                    'CostOfRevenue',
                    'CostOfGoodsAndServicesSold',
                    'CostOfGoodsSold',
                    'CostOfServices',
                ],
                'Gross Profit': ['GrossProfit'],
                'Research & Development': ['ResearchAndDevelopmentExpense'],
                'Selling, General & Admin': ['SellingGeneralAndAdministrativeExpense'],
                'Operating Expenses': ['OperatingExpenses'],
                'Operating Income': ['OperatingIncomeLoss'],
                'Interest Expense': ['InterestExpense', 'InterestExpenseDebt'],
                'Income Before Tax': [
                    'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
                    'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments',
                ],
                'Income Tax Expense': ['IncomeTaxExpenseBenefit'],
                'Net Income': [
                    'NetIncomeLoss',
                    'ProfitLoss',
                    'NetIncomeLossAvailableToCommonStockholdersBasic',
                ],
                'EPS Basic': ['EarningsPerShareBasic'],
                'EPS Diluted': ['EarningsPerShareDiluted'],
            }

            for display_name, gaap_keys in line_items.items():
                values = self._get_first_matching(us_gaap, gaap_keys, self._filter_flow_values, periods)
                if values:
                    income_statement['data'][display_name] = values

            return income_statement

        except Exception as e:
            raise Exception(f"Error getting income statement: {e}")

    def get_balance_sheet(self, ticker: str, periods: int = 4) -> Dict[str, Any]:
        """Get balance sheet for a ticker."""
        try:
            cik = get_cik_from_ticker(ticker, self.headers)
            facts = self.get_company_facts(cik)
            us_gaap = facts.get('facts', {}).get('us-gaap', {})

            balance_sheet = {
                'ticker': ticker.upper(),
                'cik': cik,
                'statement': 'Balance Sheet',
                'data': {}
            }

            line_items = {
                'Total Assets': ['Assets'],
                'Current Assets': ['AssetsCurrent'],
                'Cash and Cash Equivalents': [
                    'CashAndCashEquivalentsAtCarryingValue',
                    'CashCashEquivalentsAndShortTermInvestments',
                    'CashAndDueFromBanks',
                ],
                'Total Liabilities': ['Liabilities'],
                'Current Liabilities': ['LiabilitiesCurrent'],
                'Shareholders Equity': [
                    'StockholdersEquity',
                    'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
                ],
                'Long-term Debt': [
                    'LongTermDebt',
                    'LongTermDebtAndCapitalLeaseObligation',
                    'LongTermDebtNoncurrent',
                ],
                'Retained Earnings': ['RetainedEarningsAccumulatedDeficit'],
            }

            for display_name, gaap_keys in line_items.items():
                for gaap_key in gaap_keys:
                    if gaap_key in us_gaap:
                        units = us_gaap[gaap_key].get('units', {})
                        if 'USD' in units:
                            values = self._filter_balance_values(units['USD'], periods)
                            if values:
                                balance_sheet['data'][display_name] = values
                                break

            return balance_sheet

        except Exception as e:
            raise Exception(f"Error getting balance sheet: {e}")

    def get_cash_flow_statement(self, ticker: str, periods: int = 4) -> Dict[str, Any]:
        """Get cash flow statement for a ticker."""
        try:
            cik = get_cik_from_ticker(ticker, self.headers)
            facts = self.get_company_facts(cik)
            us_gaap = facts.get('facts', {}).get('us-gaap', {})

            cash_flow = {
                'ticker': ticker.upper(),
                'cik': cik,
                'statement': 'Cash Flow Statement',
                'data': {}
            }

            line_items = {
                'Operating Cash Flow': ['NetCashProvidedByUsedInOperatingActivities'],
                'Investing Cash Flow': ['NetCashProvidedByUsedInInvestingActivities'],
                'Financing Cash Flow': ['NetCashProvidedByUsedInFinancingActivities'],
                'Depreciation & Amortization': [
                    'DepreciationDepletionAndAmortization',
                    'DepreciationAndAmortization',
                    'Depreciation',
                ],
                'Capital Expenditures': [
                    'PaymentsToAcquirePropertyPlantAndEquipment',
                    'PaymentsForCapitalImprovements',
                ],
                'Dividends Paid': [
                    'PaymentsOfDividends',
                    'PaymentsOfDividendsCommonStock',
                ],
            }

            for display_name, gaap_keys in line_items.items():
                values = self._get_first_matching(us_gaap, gaap_keys, self._filter_flow_values, periods)
                if values:
                    cash_flow['data'][display_name] = values

            return cash_flow

        except Exception as e:
            raise Exception(f"Error getting cash flow statement: {e}")


def format_financial_statement(statement: Dict[str, Any]) -> str:
    """Format financial statement for display."""
    output = []
    output.append(f"\n{'='*80}")
    output.append(f"{statement['statement']} - {statement['ticker']}")
    output.append(f"CIK: {statement['cik']}")
    output.append(f"{'='*80}\n")

    if not statement['data']:
        return "No data available"

    for line_item, values in statement['data'].items():
        output.append(f"\n{line_item}:")
        output.append("-" * 40)

        for value in values:
            end_date = value.get('end', 'N/A')
            val = value.get('val', 0)
            filed = value.get('filed', 'N/A')
            form = value.get('form', '')

            # Determine period label
            start = value.get('start')
            if start and end_date != 'N/A':
                try:
                    days = (datetime.strptime(end_date, '%Y-%m-%d') - datetime.strptime(start, '%Y-%m-%d')).days
                    period_label = 'Annual' if days > 300 else 'Quarterly'
                except Exception:
                    period_label = form
            else:
                period_label = form  # balance sheet items have no start date

            # Format value
            if abs(val) >= 1_000_000_000:
                formatted_val = f"${val/1_000_000_000:.2f}B"
            elif abs(val) >= 1_000_000:
                formatted_val = f"${val/1_000_000:.2f}M"
            elif abs(val) < 1000:  # Likely a per-share value
                formatted_val = f"${val:.2f}"
            else:
                formatted_val = f"${val:,.0f}"

            output.append(f"  {end_date} [{period_label}, {form}]: {formatted_val} (Filed: {filed})")

    return "\n".join(output)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Get SEC financial statements')
    parser.add_argument('ticker', help='Stock ticker symbol')
    parser.add_argument('--statement', choices=['income', 'balance', 'cashflow', 'all'],
                       default='all', help='Type of financial statement')
    parser.add_argument('--periods', type=int, default=4, help='Number of periods')

    args = parser.parse_args()

    try:
        client = SECFinancialsClient()
        print(f"\nFetching {args.statement} statement(s) for {args.ticker.upper()}...\n")

        if args.statement in ['income', 'all']:
            income = client.get_income_statement(args.ticker, args.periods)
            print(format_financial_statement(income))

        if args.statement in ['balance', 'all']:
            balance = client.get_balance_sheet(args.ticker, args.periods)
            print(format_financial_statement(balance))

        if args.statement in ['cashflow', 'all']:
            cashflow = client.get_cash_flow_statement(args.ticker, args.periods)
            print(format_financial_statement(cashflow))

    except Exception as e:
        print(f"\nError: {e}")
        import sys
        sys.exit(1)


if __name__ == '__main__':
    main()

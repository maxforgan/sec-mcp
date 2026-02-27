#!/usr/bin/env python3
"""
SEC Financial Statements Parser
Extracts income statement, balance sheet, and cash flow from SEC filings.
"""

import requests
import pandas as pd
from typing import Dict, Any, Optional
from datetime import datetime


class SECFinancialsClient:
    """Client for retrieving financial statements from SEC filings."""

    BASE_URL = "https://data.sec.gov"
    COMPANY_FACTS_URL = f"{BASE_URL}/api/xbrl/companyfacts"

    def __init__(self):
        # SEC requires a user agent
        self.headers = {
            'User-Agent': 'SEC-Financials sec-financials@example.com'
        }

    def get_cik_from_ticker(self, ticker: str) -> str:
        """Get CIK number from ticker symbol."""
        # Get ticker to CIK mapping
        url = "https://www.sec.gov/files/company_tickers.json"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()

            ticker_upper = ticker.upper()
            for item in data.values():
                if item['ticker'] == ticker_upper:
                    cik = str(item['cik_str']).zfill(10)
                    return cik

            raise ValueError(f"Ticker {ticker} not found")
        except Exception as e:
            raise Exception(f"Error getting CIK: {e}")

    def get_company_facts(self, cik: str) -> Dict:
        """Get all company facts (financial data) for a CIK."""
        url = f"{self.COMPANY_FACTS_URL}/CIK{cik}.json"

        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise Exception(f"Error fetching company facts: {e}")

    def get_income_statement(self, ticker: str, periods: int = 4) -> Dict[str, Any]:
        """
        Get income statement for a ticker.

        Args:
            ticker: Stock ticker symbol
            periods: Number of periods to retrieve (default: 4)

        Returns:
            Dictionary with income statement data
        """
        try:
            cik = self.get_cik_from_ticker(ticker)
            facts = self.get_company_facts(cik)

            # Extract US-GAAP data
            us_gaap = facts.get('facts', {}).get('us-gaap', {})

            income_statement = {
                'ticker': ticker.upper(),
                'cik': cik,
                'statement': 'Income Statement',
                'data': {}
            }

            # Key income statement line items
            line_items = {
                'Revenues': 'Revenues',
                'RevenueFromContractWithCustomerExcludingAssessedTax': 'Revenues',
                'CostOfRevenue': 'Cost of Revenue',
                'CostOfGoodsAndServicesSold': 'Cost of Revenue',
                'GrossProfit': 'Gross Profit',
                'OperatingExpenses': 'Operating Expenses',
                'OperatingIncomeLoss': 'Operating Income',
                'InterestExpense': 'Interest Expense',
                'IncomeTaxExpenseBenefit': 'Income Tax Expense',
                'NetIncomeLoss': 'Net Income',
                'EarningsPerShareBasic': 'EPS Basic',
                'EarningsPerShareDiluted': 'EPS Diluted',
            }

            for gaap_key, display_name in line_items.items():
                if gaap_key in us_gaap:
                    item_data = us_gaap[gaap_key]
                    units = item_data.get('units', {})

                    # Get USD or shares data
                    if 'USD' in units:
                        values = units['USD']
                    elif 'USD/shares' in units:
                        values = units['USD/shares']
                    elif 'shares' in units:
                        values = units['shares']
                    else:
                        continue

                    # Filter for annual reports (10-K)
                    annual_values = [v for v in values if v.get('form') == '10-K']

                    # Sort by filing date and get most recent
                    annual_values.sort(key=lambda x: x.get('end', ''), reverse=True)
                    recent_values = annual_values[:periods]

                    if recent_values:
                        income_statement['data'][display_name] = recent_values

            return income_statement

        except Exception as e:
            raise Exception(f"Error getting income statement: {e}")

    def get_balance_sheet(self, ticker: str, periods: int = 4) -> Dict[str, Any]:
        """Get balance sheet for a ticker."""
        try:
            cik = self.get_cik_from_ticker(ticker)
            facts = self.get_company_facts(cik)

            us_gaap = facts.get('facts', {}).get('us-gaap', {})

            balance_sheet = {
                'ticker': ticker.upper(),
                'cik': cik,
                'statement': 'Balance Sheet',
                'data': {}
            }

            line_items = {
                'Assets': 'Total Assets',
                'AssetsCurrent': 'Current Assets',
                'CashAndCashEquivalentsAtCarryingValue': 'Cash and Cash Equivalents',
                'Liabilities': 'Total Liabilities',
                'LiabilitiesCurrent': 'Current Liabilities',
                'StockholdersEquity': 'Shareholders Equity',
                'LongTermDebt': 'Long-term Debt',
                'RetainedEarningsAccumulatedDeficit': 'Retained Earnings',
            }

            for gaap_key, display_name in line_items.items():
                if gaap_key in us_gaap:
                    item_data = us_gaap[gaap_key]
                    units = item_data.get('units', {})

                    if 'USD' in units:
                        values = units['USD']
                        annual_values = [v for v in values if v.get('form') == '10-K']
                        annual_values.sort(key=lambda x: x.get('end', ''), reverse=True)
                        recent_values = annual_values[:periods]

                        if recent_values:
                            balance_sheet['data'][display_name] = recent_values

            return balance_sheet

        except Exception as e:
            raise Exception(f"Error getting balance sheet: {e}")

    def get_cash_flow_statement(self, ticker: str, periods: int = 4) -> Dict[str, Any]:
        """Get cash flow statement for a ticker."""
        try:
            cik = self.get_cik_from_ticker(ticker)
            facts = self.get_company_facts(cik)

            us_gaap = facts.get('facts', {}).get('us-gaap', {})

            cash_flow = {
                'ticker': ticker.upper(),
                'cik': cik,
                'statement': 'Cash Flow Statement',
                'data': {}
            }

            line_items = {
                'NetCashProvidedByUsedInOperatingActivities': 'Operating Cash Flow',
                'NetCashProvidedByUsedInInvestingActivities': 'Investing Cash Flow',
                'NetCashProvidedByUsedInFinancingActivities': 'Financing Cash Flow',
                'DepreciationDepletionAndAmortization': 'Depreciation & Amortization',
                'PaymentsToAcquirePropertyPlantAndEquipment': 'Capital Expenditures',
                'PaymentsOfDividends': 'Dividends Paid',
            }

            for gaap_key, display_name in line_items.items():
                if gaap_key in us_gaap:
                    item_data = us_gaap[gaap_key]
                    units = item_data.get('units', {})

                    if 'USD' in units:
                        values = units['USD']
                        annual_values = [v for v in values if v.get('form') == '10-K']
                        annual_values.sort(key=lambda x: x.get('end', ''), reverse=True)
                        recent_values = annual_values[:periods]

                        if recent_values:
                            cash_flow['data'][display_name] = recent_values

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

            # Format value
            if abs(val) >= 1_000_000_000:
                formatted_val = f"${val/1_000_000_000:.2f}B"
            elif abs(val) >= 1_000_000:
                formatted_val = f"${val/1_000_000:.2f}M"
            elif abs(val) < 1000:  # Likely a per-share value
                formatted_val = f"${val:.2f}"
            else:
                formatted_val = f"${val:,.0f}"

            output.append(f"  Period Ending {end_date}: {formatted_val} (Filed: {filed})")

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
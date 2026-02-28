#!/usr/bin/env python3
"""
SEC Filing Table Extractor
Extracts formatted financial statement tables from SEC filing HTML.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Any
import re

from sec_utils import get_cik_from_ticker


class SECTableExtractor:
    """Extracts formatted tables from SEC filings."""

    BASE_URL = "https://www.sec.gov"

    def __init__(self):
        self.headers = {
            'User-Agent': 'SEC-MCP CLI maxforgan@google.com'
        }

    def get_latest_filing_url(self, ticker: str, filing_type: str = '10-K') -> str:
        """Get the URL of the most recent filing document of the given type."""
        cik = get_cik_from_ticker(ticker, self.headers)

        url = f"{self.BASE_URL}/cgi-bin/browse-edgar"
        params = {
            'action': 'getcompany',
            'CIK': cik,
            'type': filing_type,
            'dateb': '',
            'owner': 'exclude',
            'count': '1'
        }

        try:
            response = requests.get(url, params=params, headers=self.headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table', class_='tableFile2')
            if not table:
                raise ValueError(f"No {filing_type} filings found for {ticker.upper()}")

            doc_link = table.find('a', id='documentsbutton')
            if not doc_link:
                raise ValueError("Could not find documents link")

            doc_url = self.BASE_URL + doc_link['href']

            response = requests.get(doc_url, headers=self.headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            doc_table = soup.find('table', class_='tableFile')
            if doc_table:
                for row in doc_table.find_all('tr')[1:]:
                    cols = row.find_all('td')
                    if len(cols) >= 4:
                        doc_type = cols[3].text.strip()
                        if doc_type == filing_type:
                            link = cols[2].find('a')
                            if link:
                                href = link['href']
                                if '/ix?doc=' in href:
                                    actual_url = href.split('/ix?doc=')[1]
                                    return self.BASE_URL + actual_url
                                else:
                                    return self.BASE_URL + href

            raise ValueError(f"Could not find {filing_type} document")

        except Exception as e:
            raise Exception(f"Error getting {filing_type} URL: {e}")

    def extract_financial_tables(self, filing_url: str) -> Dict[str, Any]:
        """Extract financial statement tables from filing HTML."""
        try:
            response = requests.get(filing_url, headers=self.headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            tables = soup.find_all('table')

            financial_tables = {
                'income_statement': None,
                'balance_sheet': None,
                'cash_flow': None,
                'all_tables': []
            }

            income_keywords = ['income', 'operations', 'earnings']
            balance_keywords = ['balance', 'financial position', 'assets']
            cashflow_keywords = ['cash flow', 'cash flows']

            for idx, table in enumerate(tables):
                table_text = table.get_text().lower()

                table_info = {
                    'index': idx,
                    'type': 'unknown',
                    'html': str(table)
                }

                if any(kw in table_text for kw in income_keywords):
                    if 'per share' in table_text or 'net income' in table_text:
                        table_info['type'] = 'income_statement'
                        if not financial_tables['income_statement']:
                            financial_tables['income_statement'] = self._format_table(table)

                elif any(kw in table_text for kw in balance_keywords):
                    if 'liabilities' in table_text or 'equity' in table_text:
                        table_info['type'] = 'balance_sheet'
                        if not financial_tables['balance_sheet']:
                            financial_tables['balance_sheet'] = self._format_table(table)

                elif any(kw in table_text for kw in cashflow_keywords):
                    if 'operating' in table_text or 'investing' in table_text:
                        table_info['type'] = 'cash_flow'
                        if not financial_tables['cash_flow']:
                            financial_tables['cash_flow'] = self._format_table(table)

                financial_tables['all_tables'].append(table_info)

            return financial_tables

        except Exception as e:
            raise Exception(f"Error extracting tables: {e}")

    def _format_table(self, table) -> str:
        """Format an HTML table as text."""
        rows = []

        for tr in table.find_all('tr'):
            cells = []
            for td in tr.find_all(['td', 'th']):
                text = td.get_text(strip=True)
                text = re.sub(r'\s+', ' ', text)
                cells.append(text)

            if cells:
                rows.append(cells)

        if not rows:
            return "No data found"

        col_widths = [0] * max(len(row) for row in rows)
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(cell))

        output = []
        for row in rows:
            formatted_row = []
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    if cell.replace(',', '').replace('.', '').replace('-', '').replace('(', '').replace(')', '').replace('$', '').isdigit():
                        formatted_row.append(cell.rjust(col_widths[i]))
                    else:
                        formatted_row.append(cell.ljust(col_widths[i]))

            output.append(' | '.join(formatted_row))

        return '\n'.join(output)

    def get_income_statement_table(self, ticker: str, filing_type: str = '10-K') -> str:
        """Get formatted income statement table."""
        try:
            filing_url = self.get_latest_filing_url(ticker, filing_type=filing_type)
            tables = self.extract_financial_tables(filing_url)

            if tables['income_statement']:
                output = f"\n{'='*80}\n"
                output += f"Income Statement - {ticker.upper()}\n"
                output += f"Source: Latest {filing_type} Filing\n"
                output += f"{'='*80}\n\n"
                output += tables['income_statement']
                return output
            else:
                return f"Could not find income statement table in latest {filing_type} for {ticker.upper()}"

        except Exception as e:
            return f"Error: {str(e)}"

    def get_balance_sheet_table(self, ticker: str, filing_type: str = '10-K') -> str:
        """Get formatted balance sheet table."""
        try:
            filing_url = self.get_latest_filing_url(ticker, filing_type=filing_type)
            tables = self.extract_financial_tables(filing_url)

            if tables['balance_sheet']:
                output = f"\n{'='*80}\n"
                output += f"Balance Sheet - {ticker.upper()}\n"
                output += f"Source: Latest {filing_type} Filing\n"
                output += f"{'='*80}\n\n"
                output += tables['balance_sheet']
                return output
            else:
                return f"Could not find balance sheet table in latest {filing_type} for {ticker.upper()}"

        except Exception as e:
            return f"Error: {str(e)}"

    def get_cash_flow_table(self, ticker: str, filing_type: str = '10-K') -> str:
        """Get formatted cash flow statement table."""
        try:
            filing_url = self.get_latest_filing_url(ticker, filing_type=filing_type)
            tables = self.extract_financial_tables(filing_url)

            if tables['cash_flow']:
                output = f"\n{'='*80}\n"
                output += f"Cash Flow Statement - {ticker.upper()}\n"
                output += f"Source: Latest {filing_type} Filing\n"
                output += f"{'='*80}\n\n"
                output += tables['cash_flow']
                return output
            else:
                return f"Could not find cash flow statement table in latest {filing_type} for {ticker.upper()}"

        except Exception as e:
            return f"Error: {str(e)}"


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Extract formatted tables from SEC filings')
    parser.add_argument('ticker', help='Stock ticker symbol')
    parser.add_argument('--statement', choices=['income', 'balance', 'cashflow'],
                       default='income', help='Type of statement')
    parser.add_argument('--filing-type', default='10-K', choices=['10-K', '10-Q'],
                       help='Filing type (default: 10-K)')

    args = parser.parse_args()

    try:
        extractor = SECTableExtractor()

        if args.statement == 'income':
            print(extractor.get_income_statement_table(args.ticker, args.filing_type))
        elif args.statement == 'balance':
            print(extractor.get_balance_sheet_table(args.ticker, args.filing_type))
        elif args.statement == 'cashflow':
            print(extractor.get_cash_flow_table(args.ticker, args.filing_type))

    except Exception as e:
        print(f"Error: {e}")
        import sys
        sys.exit(1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
SEC EDGAR CLI Tool
Retrieves company filings from the SEC's EDGAR database.
"""

import argparse
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import sys


class SECClient:
    """Client for interacting with the SEC EDGAR database."""

    BASE_URL = "https://www.sec.gov"

    def __init__(self):
        # SEC requires a user agent to be set
        self.headers = {
            'User-Agent': 'SEC-MCP CLI maxforgan@google.com'
        }
        self._cik_cache = {}  # Initialize CIK cache

    def get_cik_from_ticker(self, ticker: str) -> str:
        """
        Convert a stock ticker symbol to a CIK number.
        CIK is the unique identifier used by SEC.
        """
        ticker = ticker.upper().strip()
        url = f"{self.BASE_URL}/cgi-bin/browse-edgar"
        params = {
            'action': 'getcompany',
            'CIK': ticker,
            'type': '',
            'dateb': '',
            'owner': 'exclude',
            'count': '1'
        }

        if ticker in self._cik_cache:
            return self._cik_cache[ticker]

        try:
            response = requests.get(url, params=params, headers=self.headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            company_info = soup.find('span', class_='companyName')

            if company_info:
                # Extract CIK from the company info text
                cik_text = company_info.text
                if 'CIK#:' in cik_text:
                    cik = cik_text.split('CIK#:')[1].split()[0].strip()
                    self._cik_cache[ticker] = cik.zfill(10)  # Store in cache
                    return self._cik_cache[ticker]

            raise ValueError(f"Could not find CIK for ticker: {ticker}")

        except requests.exceptions.RequestException as e:
            raise Exception(f"Error fetching CIK: {e}")

    def get_company_filings(self, ticker: str, count: int = 10, filing_type: str = None) -> List[Dict]:
        """
        Retrieve recent SEC filings for a company.

        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            count: Number of filings to retrieve (default: 10)
            filing_type: Optional filing type filter (e.g., '10-K', '10-Q', '8-K')

        Returns:
            List of dictionaries containing filing information
        """
        cik = self.get_cik_from_ticker(ticker)

        url = f"{self.BASE_URL}/cgi-bin/browse-edgar"
        params = {
            'action': 'getcompany',
            'CIK': cik,
            'type': filing_type or '',
            'dateb': '',
            'owner': 'exclude',
            'count': str(count)
        }

        try:
            response = requests.get(url, params=params, headers=self.headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract company name
            company_info = soup.find('span', class_='companyName')
            company_name = company_info.text.split('CIK#:')[0].strip() if company_info else ticker

            # Find the filings table
            filings_table = soup.find('table', class_='tableFile2')

            if not filings_table:
                return []

            filings = []
            rows = filings_table.find_all('tr')[1:]  # Skip header row

            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    filing_type = cols[0].text.strip()
                    filing_date = cols[3].text.strip()

                    # Get the documents link
                    doc_link = cols[1].find('a')
                    if doc_link:
                        doc_url = self.BASE_URL + doc_link['href']
                    else:
                        doc_url = None

                    # Get description if available
                    description = cols[2].text.strip() if len(cols) > 2 else ""

                    filings.append({
                        'company_name': company_name,
                        'ticker': ticker.upper(),
                        'cik': cik,
                        'filing_type': filing_type,
                        'filing_date': filing_date,
                        'description': description,
                        'documents_url': doc_url
                    })

            return filings

        except requests.exceptions.RequestException as e:
            raise Exception(f"Error fetching filings: {e}")


def format_filings_output(filings: List[Dict]) -> str:
    """Format the filings data for display."""
    if not filings:
        return "No filings found."

    output = []
    output.append(f"\n{'='*80}")
    output.append(f"SEC Filings for {filings[0]['company_name']} ({filings[0]['ticker']})")
    output.append(f"CIK: {filings[0]['cik']}")
    output.append(f"{'='*80}\n")

    for idx, filing in enumerate(filings, 1):
        output.append(f"{idx}. {filing['filing_type']} - Filed: {filing['filing_date']}")
        if filing['description']:
            output.append(f"   Description: {filing['description']}")
        output.append(f"   Documents: {filing['documents_url']}")
        output.append("")

    return "\n".join(output)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Retrieve SEC filings from EDGAR database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s AAPL                    # Get latest 10 filings for Apple
  %(prog)s MSFT --count 20         # Get latest 20 filings for Microsoft
  %(prog)s TSLA --type 10-K        # Get only 10-K filings for Tesla
  %(prog)s GOOGL --type 8-K -n 5   # Get latest 5 8-K filings for Alphabet
        """
    )

    parser.add_argument(
        'ticker',
        help='Stock ticker symbol (e.g., AAPL, MSFT, TSLA)'
    )

    parser.add_argument(
        '-n', '--count',
        type=int,
        default=10,
        help='Number of filings to retrieve (default: 10)'
    )

    parser.add_argument(
        '-t', '--type',
        help='Filter by filing type (e.g., 10-K, 10-Q, 8-K)'
    )

    args = parser.parse_args()

    try:
        client = SECClient()
        print(f"\nFetching SEC filings for {args.ticker.upper()}...")

        filings = client.get_company_filings(
            ticker=args.ticker,
            count=args.count,
            filing_type=args.type
        )

        print(format_filings_output(filings))

    except ValueError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
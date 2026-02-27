#!/usr/bin/env python3
"""
SEC 13F Filings Parser
Extracts 13F holdings from SEC filings.
"""

import piboufilings as pf
from typing import Dict, Any, List
import pandas as pd

class SEC13FClient:
    """Client for retrieving and parsing 13F filings."""

    def __init__(self):
        self.downloader = pf.Downloader()

    def get_latest_13f_holdings(self, ticker_or_cik: str) -> Dict[str, Any]:
        """
        Get the latest 13F holdings for a given ticker or CIK.

        Args:
            ticker_or_cik: The ticker symbol or CIK of the investment firm.

        Returns:
            A dictionary containing the holdings information.
        """
        try:
            # PibouFilings can handle both CIKs and tickers
            filing = self.downloader.get_filings_by_ticker(ticker_or_cik, "13F")
            
            if not filing:
                raise ValueError(f"No 13F filings found for {ticker_or_cik}")

            # The library returns a dictionary of filings, let's get the latest one
            latest_filing_key = list(filing.keys())[0]
            latest_filing = filing[latest_filing_key]

            if not latest_filing.holdings:
                 raise ValueError(f"Could not parse holdings from the latest 13F filing for {ticker_or_cik}")
            
            # Convert holdings to a list of dictionaries for easier use
            holdings_list = [holding.to_dict() for holding in latest_filing.holdings]
            
            return {
                "filer": latest_filing.filer,
                "period_of_report": latest_filing.period_of_report,
                "holdings": holdings_list,
            }

        except Exception as e:
            raise Exception(f"Error getting 13F holdings: {e}")

def format_13f_holdings(holdings_data: Dict[str, Any], top_n: int = 20, return_all: bool = False) -> str:

    """Format 13F holdings for display."""

    if not holdings_data or not holdings_data['holdings']:

        return "No holdings data available."



    output = []

    output.append(f"\n{'='*80}")

    output.append(f"13F Holdings for: {holdings_data['filer']}")

    output.append(f"Report Period: {holdings_data['period_of_report']}")

    output.append(f"{'='*80}\n")

    

    # Create a DataFrame for easier manipulation

    df = pd.DataFrame(holdings_data['holdings'])

    

    if return_all:

        df_display = df.sort_values(by='value', ascending=False)

        output.append("All Holdings (by value):\n")

    else:

        # Sort by value and get the top N holdings

        df_display = df.sort_values(by='value', ascending=False).head(top_n)

        output.append(f"Top {top_n} Holdings (by value):\n")

    

    # Format the DataFrame for display

    output.append(df_display[['nameOfIssuer', 'value', 'shares']].to_string(index=False))



    return "\n".join(output)

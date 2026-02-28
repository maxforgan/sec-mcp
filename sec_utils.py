#!/usr/bin/env python3
"""
Shared utilities for SEC EDGAR clients.
"""

import requests
from typing import Optional

_DEFAULT_HEADERS = {'User-Agent': 'SEC-MCP CLI maxforgan@google.com'}
_cik_cache: dict = {}


def get_cik_from_ticker(ticker: str, headers: Optional[dict] = None) -> str:
    """
    Get 10-digit zero-padded CIK number from ticker symbol.
    Uses the SEC company_tickers.json file for fast, reliable lookup.
    """
    if headers is None:
        headers = _DEFAULT_HEADERS

    ticker_upper = ticker.upper().strip()

    if ticker_upper in _cik_cache:
        return _cik_cache[ticker_upper]

    url = "https://www.sec.gov/files/company_tickers.json"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()

    for item in data.values():
        if item['ticker'] == ticker_upper:
            cik = str(item['cik_str']).zfill(10)
            _cik_cache[ticker_upper] = cik
            return cik

    raise ValueError(f"Ticker {ticker} not found")

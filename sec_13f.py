#!/usr/bin/env python3
"""
SEC 13F Filings Parser
Extracts 13F institutional holdings from SEC EDGAR directly.
No external parsing libraries required.
"""

import re
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup

from sec_utils import get_cik_from_ticker


class SEC13FClient:
    """Client for retrieving and parsing 13F filings from SEC EDGAR."""

    BASE_URL = "https://www.sec.gov"
    DATA_URL = "https://data.sec.gov"

    def __init__(self):
        self.headers = {'User-Agent': 'SEC-MCP CLI maxforgan@google.com'}

    def _resolve_cik(self, ticker_or_cik: str) -> str:
        """Resolve a ticker symbol or raw CIK to a zero-padded 10-digit CIK string."""
        cleaned = ticker_or_cik.strip()
        if re.match(r'^0*\d+$', cleaned):
            return cleaned.zfill(10)
        return get_cik_from_ticker(cleaned, self.headers)

    def _collect_13f_accessions(self, cik: str, max_quarters: int = 1) -> Tuple[str, List[Dict]]:
        """
        Return filer name plus a list of up to max_quarters 13F-HR filing records,
        most recent first. Skips 13F-HR/A amendments (superseded by original).
        """
        url = f"{self.DATA_URL}/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=self.headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        filer_name = data.get('name', cik)
        filings: List[Dict] = []

        def _harvest(forms, accessions, dates, periods):
            for i, form in enumerate(forms):
                if len(filings) >= max_quarters:
                    break
                if form == '13F-HR':  # skip amendments — original is the authoritative filing
                    filings.append({
                        'accession': accessions[i],
                        'date': dates[i],
                        'period': periods[i] if i < len(periods) else dates[i],
                    })

        recent = data.get('filings', {}).get('recent', {})
        _harvest(
            recent.get('form', []),
            recent.get('accessionNumber', []),
            recent.get('filingDate', []),
            recent.get('reportDate', []),
        )

        # If we still need more, check paginated older filings
        for filing_page in data.get('filings', {}).get('files', []):
            if len(filings) >= max_quarters:
                break
            page_url = f"{self.DATA_URL}/submissions/{filing_page['name']}"
            resp2 = requests.get(page_url, headers=self.headers, timeout=15)
            resp2.raise_for_status()
            page = resp2.json()
            _harvest(
                page.get('form', []),
                page.get('accessionNumber', []),
                page.get('filingDate', []),
                page.get('reportDate', []),
            )

        if not filings:
            raise ValueError(f"No 13F-HR filings found for CIK {cik}")

        return filer_name, filings

    def _find_infotable_url(self, cik: str, accession: str) -> str:
        """Parse the filing index page to find the URL of the raw information-table XML."""
        cik_int = int(cik)
        accession_nodash = accession.replace('-', '')
        index_url = (
            f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/"
            f"{accession_nodash}/{accession}-index.htm"
        )
        resp = requests.get(index_url, headers=self.headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', class_='tableFile')
        if not table:
            raise ValueError(f"Could not find document table in filing index {accession}")

        # Find any row described as the Information Table, then grab its raw .xml link.
        # Skip the XSL-rendered viewer (lives under /xslForm13F_*) which returns HTML, not XML.
        for row in table.find_all('tr'):
            cols = row.find_all('td')
            row_text = ' '.join(c.get_text(strip=True).upper() for c in cols)
            if 'INFORMATION TABLE' not in row_text:
                continue
            for a in row.find_all('a', href=True):
                href_lower = a['href'].lower()
                if href_lower.endswith('.xml') and 'xsl' not in href_lower:
                    raw_href = a['href']
                    if raw_href.startswith('/'):
                        return f"{self.BASE_URL}{raw_href}"
                    return raw_href

        raise ValueError(f"Could not find information table XML in filing {accession}")

    def _parse_infotable_xml(self, xml_text: str) -> List[Dict]:
        """Parse 13F infotable XML into a list of holding dicts.

        The XML value field is stored in whole dollars.
        """
        # 1. Strip xmlns declarations
        xml_clean = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', xml_text)
        # 2. Strip namespace-qualified attributes (e.g. xsi:schemaLocation)
        xml_clean = re.sub(r'\s+\w+:\w+="[^"]*"', '', xml_clean)
        # 3. Remove namespace prefixes from tag names (e.g. <n1:infoTable> → <infoTable>)
        xml_clean = re.sub(r'<(/?)[\w]+:([\w]+)', r'<\1\2', xml_clean)

        try:
            root = ET.fromstring(xml_clean)
        except ET.ParseError:
            xml_clean = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', xml_text)
            xml_clean = re.sub(r'\s+\w+:\w+="[^"]*"', '', xml_clean)
            xml_clean = re.sub(r'<(/?)[\w.-]+:([\w.-]+)', r'<\1\2', xml_clean)
            root = ET.fromstring(xml_clean)

        holdings = []
        for entry in root.iter('infoTable'):
            name = (entry.findtext('nameOfIssuer') or '').strip()
            title = (entry.findtext('titleOfClass') or '').strip()
            cusip = (entry.findtext('cusip') or '').strip()
            value_str = (entry.findtext('value') or '0').replace(',', '')

            shrs_el = entry.find('shrsOrPrnAmt')
            shares_str = '0'
            shares_type = ''
            if shrs_el is not None:
                shares_str = (shrs_el.findtext('sshPrnamt') or '0').replace(',', '')
                shares_type = (shrs_el.findtext('sshPrnamtType') or '').strip()

            try:
                value_dollars = int(value_str)
            except ValueError:
                value_dollars = 0
            try:
                shares = int(shares_str)
            except ValueError:
                shares = 0

            holdings.append({
                'name': name,
                'title': title,
                'cusip': cusip,
                'value': value_dollars,
                'shares': shares,
                'shares_type': shares_type,
            })

        return holdings

    def _fetch_quarter(self, cik: str, filing_info: Dict) -> Dict[str, Any]:
        """Fetch and parse holdings for a single quarter."""
        infotable_url = self._find_infotable_url(cik, filing_info['accession'])
        resp = requests.get(infotable_url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        return self._parse_infotable_xml(resp.text)

    def get_latest_13f_holdings(self, ticker_or_cik: str) -> Dict[str, Any]:
        """Get the latest 13F holdings for a given ticker or CIK."""
        cik = self._resolve_cik(ticker_or_cik)
        filer_name, filings = self._collect_13f_accessions(cik, max_quarters=1)
        f = filings[0]
        holdings = self._fetch_quarter(cik, f)
        return {
            'filer': filer_name,
            'cik': cik,
            'period': f['period'],
            'filing_date': f['date'],
            'accession': f['accession'],
            'holdings': holdings,
        }

    def get_holdings_history(self, ticker_or_cik: str, quarters: int = 4) -> List[Dict[str, Any]]:
        """
        Get holdings across multiple quarters, most recent first.

        Args:
            ticker_or_cik: Ticker symbol or CIK of the investment firm.
            quarters: Number of quarterly 13F filings to retrieve (default 4).

        Returns:
            List of dicts, each with filer, period, filing_date, and holdings list.
        """
        cik = self._resolve_cik(ticker_or_cik)
        filer_name, filings = self._collect_13f_accessions(cik, max_quarters=quarters)

        results = []
        for f in filings:
            holdings = self._fetch_quarter(cik, f)
            results.append({
                'filer': filer_name,
                'cik': cik,
                'period': f['period'],
                'filing_date': f['date'],
                'accession': f['accession'],
                'holdings': holdings,
            })
        return results


# ─── Formatters ────────────────────────────────────────────────────────────────

def format_13f_holdings(
    holdings_data: Dict[str, Any],
    top_n: int = 20,
    return_all: bool = False,
) -> str:
    """Format a single quarter of 13F holdings for display."""
    if not holdings_data or not holdings_data.get('holdings'):
        return "No holdings data available."

    holdings = sorted(holdings_data['holdings'], key=lambda h: h['value'], reverse=True)
    total_value = sum(h['value'] for h in holdings)
    total_positions = len(holdings)

    display = holdings if return_all else holdings[:top_n]
    header_line = "All Holdings (by value)" if return_all else f"Top {min(top_n, total_positions)} Holdings (by value)"

    lines = [
        f"\n{'='*80}",
        f"13F Holdings — {holdings_data['filer']}",
        f"Period of Report:  {holdings_data.get('period', 'N/A')}",
        f"Filed:             {holdings_data.get('filing_date', 'N/A')}",
        f"Total Positions:   {total_positions}",
        f"Total Value:       ${total_value:,.0f}",
        f"{'='*80}",
        f"\n{header_line}:\n",
        f"{'#':<4} {'Company':<40} {'Value (USD)':>15} {'Shares':>12} {'Type':<5} {'% AUM':>7}",
        f"{'-'*4} {'-'*40} {'-'*15} {'-'*12} {'-'*5} {'-'*7}",
    ]

    for rank, h in enumerate(display, 1):
        pct = (h['value'] / total_value * 100) if total_value else 0
        lines.append(
            f"{rank:<4} {h['name'][:39]:<40} ${h['value']:>14,.0f} "
            f"{h['shares']:>12,} {h['shares_type']:<5} {pct:>6.1f}%"
        )

    if not return_all and total_positions > top_n:
        lines.append(f"\n... and {total_positions - top_n} more positions. Use return_all=true to see all.")

    return '\n'.join(lines)


def format_13f_history(filings: List[Dict[str, Any]], top_n: int = 20) -> str:
    """
    Format multiple quarters of 13F holdings showing position changes over time.

    Produces:
      1. Quarterly summary table (AUM, positions count)
      2. Position changes between most recent and previous quarter
      3. Full current-quarter holdings table
    """
    if not filings:
        return "No holdings data available."

    lines = [f"\n{'='*80}"]
    lines.append(f"13F Holdings History — {filings[0]['filer']}")
    lines.append(f"Covering {len(filings)} quarter(s): "
                 f"{filings[-1]['period']} to {filings[0]['period']}")
    lines.append('='*80)

    # ── 1. Quarterly summary ────────────────────────────────────────────────────
    lines.append("\nQUARTERLY SUMMARY\n")
    lines.append(f"{'Period':<12} {'AUM':>15} {'Positions':>10}  {'Top 3 Holdings'}")
    lines.append(f"{'-'*12} {'-'*15} {'-'*10}  {'-'*40}")

    for q in filings:
        h_sorted = sorted(q['holdings'], key=lambda h: h['value'], reverse=True)
        total = sum(h['value'] for h in q['holdings'])
        top3 = ', '.join(h['name'][:18] for h in h_sorted[:3])
        lines.append(f"{q['period']:<12} ${total:>14,.0f} {len(q['holdings']):>10}  {top3}")

    # ── 2. Position changes (most recent vs prior quarter) ──────────────────────
    if len(filings) >= 2:
        cur = filings[0]
        prev = filings[1]

        # Build CUSIP-keyed dicts (fall back to name if no CUSIP)
        def key_holdings(holdings):
            out = {}
            for h in holdings:
                k = h['cusip'] if h['cusip'] else h['name']
                # Aggregate duplicate CUSIP (multiple share classes) by summing value/shares
                if k in out:
                    out[k] = dict(out[k])
                    out[k]['value'] += h['value']
                    out[k]['shares'] += h['shares']
                else:
                    out[k] = h
            return out

        cur_map = key_holdings(cur['holdings'])
        prev_map = key_holdings(prev['holdings'])

        cur_total = sum(h['value'] for h in cur['holdings'])
        prev_total = sum(h['value'] for h in prev['holdings'])

        new_keys = set(cur_map) - set(prev_map)
        closed_keys = set(prev_map) - set(cur_map)
        common_keys = set(cur_map) & set(prev_map)

        increased = []
        decreased = []
        for k in common_keys:
            c_val = cur_map[k]['value']
            p_val = prev_map[k]['value']
            if p_val == 0:
                continue
            chg_pct = (c_val - p_val) / p_val * 100
            if chg_pct >= 10:
                increased.append((k, cur_map[k]['name'], p_val, c_val, chg_pct))
            elif chg_pct <= -10:
                decreased.append((k, cur_map[k]['name'], p_val, c_val, chg_pct))

        increased.sort(key=lambda x: x[4], reverse=True)
        decreased.sort(key=lambda x: x[4])

        lines.append(f"\n\nPOSITION CHANGES  ({prev['period']} -> {cur['period']})\n")

        if new_keys:
            lines.append(f"NEW POSITIONS ({len(new_keys)}):")
            for k in sorted(new_keys, key=lambda k: cur_map[k]['value'], reverse=True):
                h = cur_map[k]
                pct = h['value'] / cur_total * 100 if cur_total else 0
                lines.append(f"  + {h['name'][:38]:<38}  ${h['value']:>13,.0f}  ({pct:.1f}% AUM)")
        else:
            lines.append("NEW POSITIONS: none")

        lines.append("")
        if closed_keys:
            lines.append(f"CLOSED POSITIONS ({len(closed_keys)}):")
            for k in sorted(closed_keys, key=lambda k: prev_map[k]['value'], reverse=True):
                h = prev_map[k]
                pct = h['value'] / prev_total * 100 if prev_total else 0
                lines.append(f"  - {h['name'][:38]:<38}  was ${h['value']:>12,.0f}  ({pct:.1f}% prior AUM)")
        else:
            lines.append("CLOSED POSITIONS: none")

        lines.append("")
        if increased:
            lines.append(f"SIGNIFICANTLY INCREASED (>=10%  |  {len(increased)} positions):")
            for k, name, p_val, c_val, chg in increased[:15]:
                lines.append(f"  (+) {name[:38]:<38}  ${p_val:>12,.0f} -> ${c_val:>12,.0f}  ({chg:+.1f}%)")
        else:
            lines.append("SIGNIFICANTLY INCREASED: none")

        lines.append("")
        if decreased:
            lines.append(f"SIGNIFICANTLY DECREASED (<=-10%  |  {len(decreased)} positions):")
            for k, name, p_val, c_val, chg in decreased[:15]:
                lines.append(f"  (-) {name[:38]:<38}  ${p_val:>12,.0f} -> ${c_val:>12,.0f}  ({chg:+.1f}%)")
        else:
            lines.append("SIGNIFICANTLY DECREASED: none")

    # ── 3. Full current holdings ────────────────────────────────────────────────
    cur = filings[0]
    cur_sorted = sorted(cur['holdings'], key=lambda h: h['value'], reverse=True)
    cur_total = sum(h['value'] for h in cur['holdings'])

    lines.append(f"\n\nCURRENT HOLDINGS — {cur['period']} (top {min(top_n, len(cur_sorted))}):\n")
    lines.append(
        f"{'#':<4} {'Company':<40} {'Value (USD)':>15} {'Shares':>12} {'% AUM':>7}"
    )
    lines.append(f"{'-'*4} {'-'*40} {'-'*15} {'-'*12} {'-'*7}")

    for rank, h in enumerate(cur_sorted[:top_n], 1):
        pct = (h['value'] / cur_total * 100) if cur_total else 0
        lines.append(
            f"{rank:<4} {h['name'][:39]:<40} ${h['value']:>14,.0f} "
            f"{h['shares']:>12,} {pct:>6.1f}%"
        )

    if len(cur_sorted) > top_n:
        lines.append(f"\n... and {len(cur_sorted) - top_n} more positions.")

    return '\n'.join(lines)

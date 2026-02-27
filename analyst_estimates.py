#!/usr/bin/env python3
"""
Analyst Estimates Client
Retrieves analyst estimates and consensus data from Yahoo Finance.
"""

import yfinance as yf
from typing import Dict, Any, Optional
import pandas as pd
from datetime import datetime


class AnalystEstimatesClient:
    """Client for retrieving analyst estimates and consensus data."""

    def get_estimates(self, ticker: str) -> Dict[str, Any]:
        """
        Retrieve comprehensive analyst estimates for a given ticker.

        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL', 'MSFT')

        Returns:
            Dictionary containing earnings estimates, revenue estimates,
            growth estimates, and earnings history
        """
        try:
            stock = yf.Ticker(ticker.upper())

            # Get company info
            info = stock.info
            company_name = info.get('longName', ticker.upper())
            current_price = info.get('currentPrice') or info.get('regularMarketPrice')

            result = {
                'ticker': ticker.upper(),
                'company_name': company_name,
                'current_price': current_price,
                'currency': info.get('currency', 'USD'),
                'earnings_estimates': self._get_earnings_estimates(stock),
                'revenue_estimates': self._get_revenue_estimates(stock),
                'eps_trend': self._get_eps_trend(stock),
                'eps_revisions': self._get_eps_revisions(stock),
                'growth_estimates': self._get_growth_estimates(stock),
                'earnings_history': self._get_earnings_history(stock),
                'analyst_info': {
                    'recommendation': info.get('recommendationKey', 'N/A'),
                    'recommendation_mean': info.get('recommendationMean'),
                    'number_of_analysts': info.get('numberOfAnalystOpinions'),
                    'target_mean_price': info.get('targetMeanPrice'),
                    'target_high_price': info.get('targetHighPrice'),
                    'target_low_price': info.get('targetLowPrice'),
                    'target_median_price': info.get('targetMedianPrice'),
                }
            }

            return result

        except Exception as e:
            raise Exception(f"Error retrieving estimates for {ticker}: {e}")

    def _get_earnings_estimates(self, stock) -> Optional[Dict]:
        """Get earnings (EPS) estimates."""
        try:
            df = stock.earnings_estimate
            if df is not None and not df.empty:
                return self._dataframe_to_dict(df)
        except:
            pass
        return None

    def _get_revenue_estimates(self, stock) -> Optional[Dict]:
        """Get revenue estimates."""
        try:
            df = stock.revenue_estimate
            if df is not None and not df.empty:
                return self._dataframe_to_dict(df)
        except:
            pass
        return None

    def _get_eps_trend(self, stock) -> Optional[Dict]:
        """Get EPS trend (revisions)."""
        try:
            df = stock.eps_trend
            if df is not None and not df.empty:
                return self._dataframe_to_dict(df)
        except:
            pass
        return None

    def _get_eps_revisions(self, stock) -> Optional[Dict]:
        """Get EPS estimate revisions."""
        try:
            df = stock.eps_revisions
            if df is not None and not df.empty:
                return self._dataframe_to_dict(df)
        except:
            pass
        return None

    def _get_growth_estimates(self, stock) -> Optional[Dict]:
        """Get growth estimates."""
        try:
            df = stock.growth_estimates
            if df is not None and not df.empty:
                return self._dataframe_to_dict(df)
        except:
            pass
        return None

    def _get_earnings_history(self, stock) -> Optional[Dict]:
        """Get historical earnings (actual vs estimate)."""
        try:
            df = stock.earnings_history
            if df is not None and not df.empty:
                return self._dataframe_to_dict(df)
        except:
            pass
        return None

    def _dataframe_to_dict(self, df: pd.DataFrame) -> Dict:
        """Convert pandas DataFrame to dictionary with proper formatting."""
        try:
            # Reset index to make it a column
            df_reset = df.reset_index()

            # Convert to dict with records orientation
            result = df_reset.to_dict('records')

            # Clean up NaN values
            cleaned_result = []
            for record in result:
                cleaned_record = {}
                for key, value in record.items():
                    if pd.isna(value):
                        cleaned_record[key] = None
                    elif isinstance(value, (pd.Timestamp, datetime)):
                        cleaned_record[key] = value.strftime('%Y-%m-%d')
                    else:
                        cleaned_record[key] = value
                cleaned_result.append(cleaned_record)

            return cleaned_result
        except Exception as e:
            return {'error': str(e)}


def format_estimates_output(data: Dict[str, Any]) -> str:
    """Format the estimates data for display."""

    output = []
    output.append(f"\n{'='*80}")
    output.append(f"Analyst Estimates for {data['company_name']} ({data['ticker']})")
    output.append(f"Current Price: {data['currency']} {data['current_price']:.2f}" if data['current_price'] else "Current Price: N/A")
    output.append(f"{'='*80}\n")

    # Analyst Recommendations
    analyst_info = data['analyst_info']
    if analyst_info:
        output.append("ANALYST RECOMMENDATIONS")
        output.append("-" * 40)
        output.append(f"Recommendation: {analyst_info['recommendation'].upper()}")
        if analyst_info['recommendation_mean']:
            output.append(f"Recommendation Score: {analyst_info['recommendation_mean']:.2f} (1=Strong Buy, 5=Sell)")
        if analyst_info['number_of_analysts']:
            output.append(f"Number of Analysts: {analyst_info['number_of_analysts']}")
        output.append("")

        output.append("PRICE TARGETS")
        output.append("-" * 40)
        if analyst_info['target_mean_price']:
            output.append(f"Mean Target: {data['currency']} {analyst_info['target_mean_price']:.2f}")
        if analyst_info['target_median_price']:
            output.append(f"Median Target: {data['currency']} {analyst_info['target_median_price']:.2f}")
        if analyst_info['target_high_price']:
            output.append(f"High Target: {data['currency']} {analyst_info['target_high_price']:.2f}")
        if analyst_info['target_low_price']:
            output.append(f"Low Target: {data['currency']} {analyst_info['target_low_price']:.2f}")

        if data['current_price'] and analyst_info['target_mean_price']:
            upside = ((analyst_info['target_mean_price'] - data['current_price']) / data['current_price']) * 100
            output.append(f"Implied Upside: {upside:+.2f}%")
        output.append("")

    # Earnings Estimates
    if data['earnings_estimates']:
        output.append("EARNINGS (EPS) ESTIMATES")
        output.append("-" * 40)
        output.append(format_table(data['earnings_estimates']))
        output.append("")

    # Revenue Estimates
    if data['revenue_estimates']:
        output.append("REVENUE ESTIMATES")
        output.append("-" * 40)
        output.append(format_table(data['revenue_estimates']))
        output.append("")

    # EPS Trend
    if data['eps_trend']:
        output.append("EPS TREND (Estimate Revisions)")
        output.append("-" * 40)
        output.append(format_table(data['eps_trend']))
        output.append("")

    # EPS Revisions
    if data['eps_revisions']:
        output.append("EPS REVISIONS")
        output.append("-" * 40)
        output.append(format_table(data['eps_revisions']))
        output.append("")

    # Growth Estimates
    if data['growth_estimates']:
        output.append("GROWTH ESTIMATES")
        output.append("-" * 40)
        output.append(format_table(data['growth_estimates']))
        output.append("")

    # Earnings History
    if data['earnings_history']:
        output.append("EARNINGS HISTORY (Actual vs Estimate)")
        output.append("-" * 40)
        output.append(format_table(data['earnings_history']))
        output.append("")

    return "\n".join(output)


def format_table(data: list) -> str:
    """Format list of dicts as a simple table."""
    if not data:
        return "No data available"

    lines = []

    # Get all keys
    keys = list(data[0].keys())

    # Format each record
    for record in data:
        line_parts = []
        for key in keys:
            value = record.get(key)
            if value is None:
                formatted_value = "N/A"
            elif isinstance(value, float):
                formatted_value = f"{value:.2f}"
            else:
                formatted_value = str(value)

            line_parts.append(f"{key}: {formatted_value}")

        lines.append("  " + " | ".join(line_parts))

    return "\n".join(lines)


def main():
    """CLI entry point for testing."""
    import argparse

    parser = argparse.ArgumentParser(description='Get analyst estimates for a stock')
    parser.add_argument('ticker', help='Stock ticker symbol')
    args = parser.parse_args()

    try:
        client = AnalystEstimatesClient()
        print(f"\nFetching analyst estimates for {args.ticker.upper()}...")

        estimates = client.get_estimates(args.ticker)
        print(format_estimates_output(estimates))

    except Exception as e:
        print(f"\nError: {e}")
        import sys
        sys.exit(1)


if __name__ == '__main__':
    main()
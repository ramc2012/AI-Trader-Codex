"""
Test script to validate data availability for Bloomberg-grade watchlist.
Tests historical data, quotes, options chain, and all analytics features.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.integrations.fyers_client import FyersClient
from src.utils.logger import get_logger, setup_logging
from src.watchlist.data_collector import IndexDataCollector
from src.watchlist.indices import INDIAN_INDICES
from src.watchlist.options_analytics import BlackScholes

logger = get_logger(__name__)


class WatchlistDataTester:
    """Comprehensive data availability tester."""

    def __init__(self):
        setup_logging()
        self.client = FyersClient()
        self.collector = IndexDataCollector(self.client)
        self.results = {
            "test_time": datetime.now().isoformat(),
            "total_tests": 0,
            "passed_tests": 0,
            "failed_tests": 0,
            "results_by_index": {},
        }

    async def test_all(self):
        """Run all tests."""
        print("\n" + "=" * 80)
        print("BLOOMBERG-GRADE WATCHLIST DATA AVAILABILITY TEST")
        print("=" * 80 + "\n")

        # Test 1: Index Quotes
        await self.test_index_quotes()

        # Test 2: Historical Data
        await self.test_historical_data()

        # Test 3: Options Chain
        await self.test_options_chain()

        # Test 4: Greeks Calculation
        await self.test_greeks_calculation()

        # Test 5: Comprehensive Data Test
        await self.test_comprehensive_data()

        # Print Summary
        self.print_summary()

    async def test_index_quotes(self):
        """Test real-time quotes for all indices."""
        print("\n[TEST 1] Real-Time Quotes for All Indices")
        print("-" * 80)

        for name, idx in INDIAN_INDICES.items():
            self.results["total_tests"] += 1

            try:
                # Test spot quote
                spot_data = await self.collector.fetch_current_quote(idx.spot_symbol)

                if spot_data and spot_data.ltp > 0:
                    print(f"✓ {idx.display_name:20} Spot: {spot_data.ltp:10.2f}  "
                          f"Change: {spot_data.change_pct:+6.2f}% "
                          f"Volume: {spot_data.volume:,}")
                    self.results["passed_tests"] += 1

                    # Test futures quote
                    futures_data = await self.collector.fetch_current_quote(
                        idx.futures_symbol
                    )
                    if futures_data:
                        print(f"  Futures: {futures_data.ltp:10.2f}  OI: {futures_data.oi:,}")
                else:
                    print(f"✗ {idx.display_name:20} - No data")
                    self.results["failed_tests"] += 1

            except Exception as exc:
                print(f"✗ {idx.display_name:20} - Error: {exc}")
                self.results["failed_tests"] += 1

            await asyncio.sleep(0.2)  # Rate limiting

    async def test_historical_data(self):
        """Test historical data availability."""
        print("\n[TEST 2] Historical Data (Last 30 Days)")
        print("-" * 80)

        to_date = datetime.now()
        from_date = to_date - timedelta(days=30)

        for name, idx in INDIAN_INDICES.items():
            self.results["total_tests"] += 1

            try:
                df = await self.collector.fetch_historical_ohlc(
                    idx.spot_symbol, from_date, to_date, resolution="D"
                )

                if df is not None and len(df) > 0:
                    first_date = df.index[0].strftime("%Y-%m-%d")
                    last_date = df.index[-1].strftime("%Y-%m-%d")
                    print(f"✓ {idx.display_name:20} {len(df):3} days  "
                          f"From: {first_date} To: {last_date}")
                    self.results["passed_tests"] += 1
                else:
                    print(f"✗ {idx.display_name:20} - No historical data")
                    self.results["failed_tests"] += 1

            except Exception as exc:
                print(f"✗ {idx.display_name:20} - Error: {exc}")
                self.results["failed_tests"] += 1

            await asyncio.sleep(0.2)

    async def test_options_chain(self):
        """Test options chain availability."""
        print("\n[TEST 3] Options Chain Availability")
        print("-" * 80)

        # Test for major indices only
        test_indices = ["NIFTY", "BANKNIFTY", "FINNIFTY"]

        for name in test_indices:
            self.results["total_tests"] += 1

            try:
                idx = INDIAN_INDICES[name]
                chain = self.client.get_option_chain(symbol=idx.spot_symbol)

                if chain and "data" in chain:
                    expiries = chain["data"].get("expiryData", [])
                    print(f"✓ {idx.display_name:20} Options Chain Available  "
                          f"Expiries: {len(expiries)}")
                    self.results["passed_tests"] += 1
                else:
                    print(f"✗ {idx.display_name:20} - No options chain")
                    self.results["failed_tests"] += 1

            except Exception as exc:
                print(f"✗ {idx.display_name:20} - Error: {exc}")
                self.results["failed_tests"] += 1

            await asyncio.sleep(0.3)

    async def test_greeks_calculation(self):
        """Test Greeks calculation."""
        print("\n[TEST 4] Options Greeks Calculation")
        print("-" * 80)

        # Test Greeks calculation with sample data
        test_cases = [
            {"spot": 21500, "strike": 21500, "days": 7, "iv": 0.15, "type": "CE"},
            {"spot": 21500, "strike": 21000, "days": 7, "iv": 0.18, "type": "PE"},
            {"spot": 45000, "strike": 45000, "days": 14, "iv": 0.12, "type": "CE"},
        ]

        for case in test_cases:
            self.results["total_tests"] += 1

            try:
                time_to_expiry = case["days"] / 365.0
                greeks = BlackScholes.calculate_greeks(
                    spot=case["spot"],
                    strike=case["strike"],
                    time_to_expiry=time_to_expiry,
                    volatility=case["iv"],
                    option_type=case["type"],
                )

                print(f"✓ Spot: {case['spot']:7.0f} Strike: {case['strike']:7.0f} "
                      f"{case['type']} Days: {case['days']:2}  "
                      f"Delta: {greeks.delta:+6.3f} Gamma: {greeks.gamma:.5f} "
                      f"Theta: {greeks.theta:+7.2f}")
                self.results["passed_tests"] += 1

            except Exception as exc:
                print(f"✗ Greeks calculation failed: {exc}")
                self.results["failed_tests"] += 1

    async def test_comprehensive_data(self):
        """Run comprehensive data availability test."""
        print("\n[TEST 5] Comprehensive Data Availability Test")
        print("-" * 80)

        try:
            results = await self.collector.test_data_availability()

            summary = results["summary"]
            print(f"\nTotal Indices: {summary['total_indices']}")
            print(f"Spot Data Available: {summary['spot_data_available']}")
            print(f"Futures Data Available: {summary['futures_data_available']}")
            print(f"Historical Data Available: {summary['historical_data_available']}")

            # Detailed results
            print("\nDetailed Results:")
            for name, idx_result in results["indices"].items():
                spot_status = "✓" if idx_result["spot"]["available"] else "✗"
                fut_status = "✓" if idx_result["futures"]["available"] else "✗"
                hist_status = "✓" if idx_result["historical"]["available"] else "✗"

                print(f"{name:12} | Spot: {spot_status} | Futures: {fut_status} | "
                      f"Historical: {hist_status}")

            self.results["total_tests"] += 1
            self.results["passed_tests"] += 1

        except Exception as exc:
            print(f"✗ Comprehensive test failed: {exc}")
            self.results["failed_tests"] += 1

    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)

        total = self.results["total_tests"]
        passed = self.results["passed_tests"]
        failed = self.results["failed_tests"]
        pass_rate = (passed / total * 100) if total > 0 else 0

        print(f"\nTotal Tests: {total}")
        print(f"Passed: {passed} ({pass_rate:.1f}%)")
        print(f"Failed: {failed}")

        if pass_rate >= 80:
            print("\n✓ Data availability is GOOD - Ready for trading decisions")
        elif pass_rate >= 60:
            print("\n⚠ Data availability is MODERATE - Some features may be limited")
        else:
            print("\n✗ Data availability is POOR - Check data sources")

        print("\n" + "=" * 80 + "\n")


async def main():
    """Main test runner."""
    tester = WatchlistDataTester()

    if not tester.client.is_authenticated:
        print("ERROR: Fyers client is not authenticated.")
        print("Please run the authentication flow first.")
        sys.exit(1)

    await tester.test_all()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        sys.exit(1)

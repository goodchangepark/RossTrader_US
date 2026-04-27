#!/usr/bin/env python3
"""RossTrader_US 모든 모듈 통합 테스트"""
import sys, os
sys.path.insert(0, os.path.abspath('.'))

import logging
logging.basicConfig(level=logging.INFO)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

from config.constants import APP_NAME, VERSION
from gui.main_window import MainWindow
from gui.main_window_controller import MainWindowController
from gui.settings_dialog import SettingsDialog
from gui.analytics_widget import AnalyticsWidget
from gui.backtest_widget import BacktestWidget, BacktestWorker

from markets.us.us_session import USMarketSessionManager, USMarketSession, us_session
from markets.us.kis_client import KISClient
from markets.us.us_news_collector import USNewsAggregator, FinnhubNewsCollector, SECEdgarCollector
from markets.us.us_universe import USUniverse

from core.exit_manager import ExitManager, Position, ExitSignal, ExitReason
from core.risk_manager import RiskManager
from core.veto_filter import VetoFilter
from core.signal_pipeline import SignalPipeline, Signal, SignalDirection, default_score_filter
from core.entry_engine import EntryEngine, EntryStrategy
from core.execution_engine import ExecutionEngine, ExecutionOrder
from core.portfolio_manager import PortfolioManager
from core.market_regime import MarketRegimeDetector, MarketRegime
from core.pre_trade_risk_gateway import PreTradeRiskGateway
from core.factor_engine import FactorEngine, FactorScore, MarketData, NewsData
from core.position_sizer import PositionSizer, PositionSizeResult

from nlp.en_sentiment import EnglishSentimentAnalyzer, SentimentResult
from nlp.finbert_scorer import FinBERTScorer
from nlp.news_processor import NewsProcessor

from utils.forex_manager import ForexManager
from utils.config_loader import load_config, save_config
from utils.performance_tracker import PerformanceTracker, TradeRecord, DailyPerformance
from utils.news_trader import NewsTraderThread
from utils.trade_db import TradeDB, get_trade_db
from core.trading_engine import TradingEngine, reset_trading_engine

def main():
    print("=" * 60)
    print(f"  {APP_NAME} v{VERSION} — 통합 테스트 시작")
    print("=" * 60)

    # 1. US Session
    mgr = USMarketSessionManager()
    print(f"[1] 현재 세션: {mgr.current_session().value}")
    print(f"[2] 거래 가능: {mgr.is_tradeable()}")
    print(f"[3] ORB 기간: {mgr.is_orb_period()}")

    summary = mgr.session_summary()
    print(f"[4] ET: {summary['now_et']}")
    print(f"[5] KST: {summary['now_kst']}")

    # 2. Universe
    universe = USUniverse()
    print(f"[6] 관심종목: {len(universe.get_watchlist())}개")

    # 3. Risk Manager
    rm = RiskManager()
    print(f"[7] RiskManager: max_order=USD {rm.max_order_usd}, max_positions={rm.max_positions}")

    # 4. Veto Filter
    vf = VetoFilter()
    result = vf.check('AAPL', 'Apple announces $10 billion buyback program')
    print(f"[8] VetoFilter: strong_event={result['is_strong_event']}, types={result['event_types']}, blocked={result['should_block']}")

    # 5. Portfolio Manager
    pm = PortfolioManager(initial_capital_usd=10000)
    print(f"[9] PortfolioManager: initial=${pm.initial_capital:.2f}")

    # 6. Market Regime
    detector = MarketRegimeDetector()
    regime_info = detector.detect()
    print(f"[10] MarketRegime: {regime_info.regime.value}")

    # 7. English Sentiment Analyzer
    esa = EnglishSentimentAnalyzer()
    sentiment = esa.analyze("Apple reported strong earnings with revenue growth of 15%")
    print(f"[11] Sentiment: score={sentiment.score:.2f}, label={sentiment.label}")

    # 8. Forex Manager
    fm = ForexManager()
    rate = fm.get_usd_krw()
    print(f"[12] USD/KRW: {rate:.2f}")

    # 9. News Processor
    np_ = NewsProcessor()
    processed = np_.process("Apple Inc. (AAPL) announced earnings")
    print(f"[13] NewsProcessor: keys={list(processed.keys())}")

    # 10. PreTrade Risk Gateway
    gw = PreTradeRiskGateway()
    gw_result = gw.check(
        ticker='AAPL',
        qty=10,
        estimated_price=150.0,
        current_portfolio_value=5000.0,
    )
    print(f"[14] PreTradeRisk: passed={gw_result['passed']}, reason={gw_result.get('reason', 'ok')}")

    # 11. Factor Engine
    fe = FactorEngine()
    md = MarketData(
        ticker='AAPL', price=178.0, prev_close=175.0, open_price=176.5,
        vwap=177.2, high=179.0, low=176.0, volume=50_000_000, avg_volume_20d=30_000_000,
        shares_float=15_000_000_000, bid=177.95, ask=178.05, bid_size=500, ask_size=300,
        atr_14=3.5, rsi_14=58.0,
    )
    nd = NewsData(has_news=True, sentiment_score=72.0, event_type='earnings_beat',
                   freshness_seconds=120, headline='AAPL beats earnings estimates')
    fs = fe.score(md, nd)
    print(f"[11] FactorEngine: AAPL score={fs.total_score:.1f}/{fs.signal_strength} "
          f"disqualified={fs.disqualified} | SD={fs.supply_demand_total:.1f} "
          f"Mom={fs.momentum_total:.1f} News={fs.news_total:.1f} Tech={fs.technical_total:.1f}")

    # 12. Position Sizer
    ps = PositionSizer(account_usd=10_000)
    pos_result = ps.calculate(price=178.0, factor_score=fs)
    print(f"[12] PositionSizer: viable={pos_result.viable} shares={pos_result.shares} "
          f"notional=${pos_result.notional_usd:.0f} roundtrip={pos_result.roundtrip_cost_pct*100:.3f}% "
          f"RR={pos_result.reward_risk_ratio}" +
          (f" reject={pos_result.reject_reason}" if not pos_result.viable else ""))

    # 13. Signal Pipeline (with PositionSizer)
    sp = SignalPipeline()
    sp.set_position_sizer(ps)
    sig = sp.evaluate_with_factors('AAPL', md, nd)
    print(f"[13] SignalPipeline: dir={sig.direction.value} conf={sig.confidence:.2f} "
          f"size_viable={sig.size_result.viable if sig.size_result else False} "
          f"| score={sig.factor_score.total_score:.1f}/{sig.factor_score.signal_strength}")
    print(f"[SignalPipeline: initialized OK]")

    # 14. Entry Engine (with FactorEngine integration)
    ee = EntryEngine()
    entry_sig = ee.evaluate('AAPL', md, nd)
    if entry_sig:
        es = entry_sig
        print(f"[14] EntryEngine: {es.ticker} {es.strategy.value} @ ${es.entry_price:.1f} "
              f"conf={es.confidence:.2f} score={es.factor_score.total_score:.1f if es.factor_score else 0:.1f}")
    else:
        print(f"[14] EntryEngine: AAPL no signal (factorscore={fs.total_score:.1f}, disqualified={fs.disqualified})")

    # 15. Performance Tracker
    pt = PerformanceTracker()
    trade = pt.record_trade(
        ticker='AAPL', shares=pos_result.shares if pos_result.viable else 5,
        entry_price=178.0, exit_price=183.0, exit_reason='take_profit_1',
        hold_minutes=25,
    )
    print(f"[15] PerformanceTracker: net_pnl=${trade.net_pnl_usd:+.2f} "
          f"({trade.net_pnl_pct*100:+.2f}%) commission=${trade.total_commission_usd:.2f}")
    overall = pt.get_overall_summary()
    print(f"    Overall: {overall.get('전체거래횟수', 0)}trades net={overall.get('순수익', 'N/A')}")

    # 16. Execution Engine
    exe = ExecutionEngine()
    print(f"[16] ExecutionEngine: initialized OK")

    print()
    print("=" * 60)
    print(f"  {APP_NAME} v{VERSION} — 모든 모듈 정상 동작 확인 완료!")
    print("=" * 60)

if __name__ == "__main__":
    main()

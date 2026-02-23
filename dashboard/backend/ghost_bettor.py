"""
Ghost Bettor Engine

Automatically places paper bets when recommendations meet configured thresholds.
Tracks performance and calculates ROI.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session

from database import (
    SessionLocal,
    GhostBet,
    GhostBettorConfig,
    BettingRecommendation,
    BetStatus,
    BetType,
    Game,
)


class GhostBettor:
    """
    Paper trading system that automatically places bets based on recommendations.
    """

    def __init__(self, db: Session = None):
        self.db = db or SessionLocal()

    def get_config(self) -> GhostBettorConfig:
        """Get current ghost bettor configuration."""
        config = self.db.query(GhostBettorConfig).first()
        if not config:
            config = GhostBettorConfig()
            self.db.add(config)
            self.db.commit()
            self.db.refresh(config)
        return config

    def update_config(self, **kwargs) -> GhostBettorConfig:
        """Update ghost bettor configuration."""
        config = self.get_config()
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        config.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(config)
        return config

    def should_bet(self, recommendation: BettingRecommendation) -> bool:
        """Check if a recommendation meets thresholds for auto-betting."""
        config = self.get_config()

        if not config.is_active:
            return False

        if recommendation.bet_type == BetType.TOTAL:
            return (
                recommendation.edge >= config.total_min_edge and
                recommendation.probability >= config.total_min_prob
            )
        elif recommendation.bet_type == BetType.SPREAD:
            return (
                recommendation.edge >= config.spread_min_edge and
                recommendation.probability >= config.spread_min_prob
            )
        elif recommendation.bet_type == BetType.MONEYLINE:
            return (
                recommendation.edge >= config.ml_min_edge and
                recommendation.probability >= config.ml_min_prob
            )
        return False

    def calculate_payout(self, bet_amount: float, odds: int) -> float:
        """Calculate potential payout based on American odds."""
        if odds > 0:
            return bet_amount * (odds / 100)
        else:
            return bet_amount * (100 / abs(odds))

    def place_bet(self, recommendation: BettingRecommendation, game: Game) -> Optional[GhostBet]:
        """Place a ghost bet for a recommendation."""
        if not self.should_bet(recommendation):
            return None

        config = self.get_config()

        # Check daily limit
        today = datetime.utcnow().date()
        today_bets = self.db.query(GhostBet).filter(
            GhostBet.created_at >= datetime(today.year, today.month, today.day)
        ).count()
        if today_bets >= config.max_bets_per_day:
            return None

        # Check per-game limit
        game_bets = self.db.query(GhostBet).filter(
            GhostBet.game_id == game.id
        ).count()
        if game_bets >= config.max_bets_per_game:
            return None

        # Check bankroll
        if config.current_bankroll < config.default_bet_amount:
            return None

        # Calculate potential payout
        potential_payout = self.calculate_payout(config.default_bet_amount, recommendation.odds or -110)

        # Create ghost bet
        bet = GhostBet(
            game_id=game.id,
            recommendation_id=recommendation.id,
            bet_type=recommendation.bet_type,
            pick=recommendation.pick,
            line=recommendation.line,
            odds=recommendation.odds,
            edge=recommendation.edge,
            probability=recommendation.probability,
            confidence_tier=recommendation.confidence_tier,
            bet_amount=config.default_bet_amount,
            potential_payout=potential_payout,
            result=BetStatus.PENDING,
        )

        # Deduct from bankroll
        config.current_bankroll -= config.default_bet_amount

        self.db.add(bet)
        self.db.commit()
        self.db.refresh(bet)

        return bet

    def process_recommendations(self, recommendations: List[BettingRecommendation], game: Game) -> List[GhostBet]:
        """Process multiple recommendations and place bets for qualifying ones."""
        bets = []
        for rec in recommendations:
            bet = self.place_bet(rec, game)
            if bet:
                bets.append(bet)
        return bets

    def resolve_bet(self, bet: GhostBet, won: bool, push: bool = False) -> GhostBet:
        """Resolve a ghost bet based on game outcome."""
        config = self.get_config()

        if push:
            bet.result = BetStatus.PUSH
            bet.actual_payout = bet.bet_amount  # Return stake
            config.current_bankroll += bet.bet_amount
        elif won:
            bet.result = BetStatus.WON
            bet.actual_payout = bet.bet_amount + bet.potential_payout
            config.current_bankroll += bet.actual_payout
        else:
            bet.result = BetStatus.LOST
            bet.actual_payout = 0.0
            # Bankroll already deducted when bet was placed

        bet.resolved_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(bet)
        return bet

    def get_pending_bets(self) -> List[GhostBet]:
        """Get all pending ghost bets."""
        return self.db.query(GhostBet).filter(
            GhostBet.result == BetStatus.PENDING
        ).all()

    def get_stats(self, days: int = 30) -> dict:
        """Get ghost bettor performance statistics."""
        cutoff = datetime.utcnow() - timedelta(days=days)

        bets = self.db.query(GhostBet).filter(
            GhostBet.created_at >= cutoff
        ).all()

        config = self.get_config()

        total_bets = len(bets)
        won = len([b for b in bets if b.result == BetStatus.WON])
        lost = len([b for b in bets if b.result == BetStatus.LOST])
        pending = len([b for b in bets if b.result == BetStatus.PENDING])
        push = len([b for b in bets if b.result == BetStatus.PUSH])

        total_wagered = sum(b.bet_amount for b in bets if b.result != BetStatus.PENDING)
        total_return = sum(b.actual_payout for b in bets if b.result != BetStatus.PENDING)
        profit_loss = total_return - total_wagered
        roi = (profit_loss / total_wagered * 100) if total_wagered > 0 else 0

        # By bet type
        by_type = {}
        for bet_type in BetType:
            type_bets = [b for b in bets if b.bet_type == bet_type]
            type_won = len([b for b in type_bets if b.result == BetStatus.WON])
            type_resolved = len([b for b in type_bets if b.result in (BetStatus.WON, BetStatus.LOST)])
            by_type[bet_type.value] = {
                "total": len(type_bets),
                "won": type_won,
                "win_rate": (type_won / type_resolved * 100) if type_resolved > 0 else 0,
            }

        # By confidence tier
        by_tier = {}
        for tier in ["A+", "A", "B+", "B"]:
            tier_bets = [b for b in bets if b.confidence_tier == tier]
            tier_won = len([b for b in tier_bets if b.result == BetStatus.WON])
            tier_resolved = len([b for b in tier_bets if b.result in (BetStatus.WON, BetStatus.LOST)])
            by_tier[tier] = {
                "total": len(tier_bets),
                "won": tier_won,
                "win_rate": (tier_won / tier_resolved * 100) if tier_resolved > 0 else 0,
            }

        return {
            "period_days": days,
            "total_bets": total_bets,
            "won": won,
            "lost": lost,
            "pending": pending,
            "push": push,
            "win_rate": (won / (won + lost) * 100) if (won + lost) > 0 else 0,
            "total_wagered": total_wagered,
            "total_return": total_return,
            "profit_loss": profit_loss,
            "roi": roi,
            "current_bankroll": config.current_bankroll,
            "starting_bankroll": config.starting_bankroll,
            "by_type": by_type,
            "by_tier": by_tier,
        }

    def get_recent_bets(self, limit: int = 20) -> List[GhostBet]:
        """Get recent ghost bets."""
        return self.db.query(GhostBet).order_by(
            GhostBet.created_at.desc()
        ).limit(limit).all()

    def get_bankroll_history(self, days: int = 30) -> List[dict]:
        """Get bankroll history over time."""
        from database import PerformanceSnapshot

        cutoff = datetime.utcnow() - timedelta(days=days)
        snapshots = self.db.query(PerformanceSnapshot).filter(
            PerformanceSnapshot.snapshot_date >= cutoff
        ).order_by(PerformanceSnapshot.snapshot_date).all()

        return [
            {
                "date": s.snapshot_date.isoformat(),
                "bankroll": s.bankroll,
                "profit_loss": s.profit_loss,
            }
            for s in snapshots
        ]


# Singleton instance
_ghost_bettor: Optional[GhostBettor] = None


def get_ghost_bettor() -> GhostBettor:
    """Get or create ghost bettor instance."""
    global _ghost_bettor
    if _ghost_bettor is None:
        _ghost_bettor = GhostBettor()
    return _ghost_bettor

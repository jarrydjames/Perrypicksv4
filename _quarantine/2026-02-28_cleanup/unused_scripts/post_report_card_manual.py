#!/usr/bin/env python3
"""
Manually post a report card for a specific date.

Usage:
    python post_report_card_manual.py [date]
    
    date: Optional date in YYYY-MM-DD format (defaults to yesterday)
    
Examples:
    python post_report_card_manual.py              # Yesterday's report card
    python post_report_card_manual.py 2026-02-27  # Specific date
"""

import sys
import os
from datetime import datetime, date

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    import logging
    from src.automation.report_card import generate_daily_report_card
    from src.automation.channel_router import create_router_from_env
    
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Parse date
    if len(sys.argv) > 1:
        # User provided date
        try:
            report_date = datetime.strptime(sys.argv[1], "%Y-%m-%d")
        except ValueError:
            print(f"Error: Invalid date format '{sys.argv[1]}'. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        # Default to yesterday
        report_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        report_date = report_date.replace(day=report_date.day - 1)
    
    logger.info(f"Generating report card for: {report_date.strftime('%Y-%m-%d')}")
    
    # Generate report card
    try:
        report = generate_daily_report_card(report_date)
        logger.info("Report card generated successfully")
        print("\n" + "="*60)
        print(report)
        print("="*60 + "\n")
    except Exception as e:
        logger.error(f"Failed to generate report card: {e}")
        print(f"Error: {e}")
        sys.exit(1)
    
    # Post to Discord
    try:
        router = create_router_from_env()
        result = router.post_report_card(report)
        
        if result and result.success:
            logger.info(f"✅ Report card posted successfully!")
            logger.info(f"Message ID: {result.message_id}")
        else:
            error = result.error if result else "Unknown error"
            logger.error(f"Failed to post report card: {error}")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Failed to post report card: {e}")
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

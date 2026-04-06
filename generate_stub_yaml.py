#!/usr/bin/env python3
"""
Generate stub YAML configuration file for a caldip directory.

Usage:
    python generate_stub_yaml.py <directory>
    python generate_stub_yaml.py --print-only <directory>
"""

import sys
import argparse
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from caldip.readers import generate_stub_yaml


def main():
    parser = argparse.ArgumentParser(
        description="Generate stub YAML configuration for caldip directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate YAML file in directory
  python generate_stub_yaml.py data/proc_calib/cruise123/cal_dip/castM3
  
  # Print to stdout without writing file
  python generate_stub_yaml.py --print-only data/proc_calib/cruise123/cal_dip/castM3
        """,
    )

    parser.add_argument(
        "directory",
        help="Path to caldip directory containing CTD and instrument files"
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print YAML to stdout instead of writing file"
    )

    args = parser.parse_args()

    try:
        config = generate_stub_yaml(args.directory, print_only=args.print_only)
        
        if not args.print_only:
            print(f"\n✅ Successfully generated stub YAML for {args.directory}")
            print(f"📁 Found {len(config.get('instruments', []))} instruments")
            if config.get('deployment_time'):
                print(f"📅 Deployment time: {config['deployment_time']}")
            if config.get('deployment_latitude'):
                print(f"🌍 Position: {config['deployment_latitude']}, {config['deployment_longitude']}")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
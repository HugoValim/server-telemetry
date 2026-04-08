import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="Example CLI: compute basic stats")
    parser.add_argument(
        "nums",
        metavar="N",
        type=float,
        nargs="+",
        help="Numbers to analyze (e.g. 1 2 3.5)",
    )
    parser.add_argument("--mode", choices=["sum", "mean", "min", "max"], default="mean")

    args = parser.parse_args()
    nums = args.nums

    if args.mode == "sum":
        out = sum(nums)
    elif args.mode == "mean":
        out = sum(nums) / len(nums)
    elif args.mode == "min":
        out = min(nums)
    else:  # max
        out = max(nums)

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

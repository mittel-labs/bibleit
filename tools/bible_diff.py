import argparse


def get_name(translation):
    return f"diff.{translation}.chapters.count"


def diff(a, b):
    na, nb = map(get_name, [a, b])
    with open(na) as ba, open(nb) as bb:
        for x, y in zip(ba, bb):
            xx, yy = x.split("$")[1].strip(), y.split("$")[1].strip()
            if xx != yy:
                print(x.strip(), y.strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bible differences")
    parser.add_argument("a", help="left")
    parser.add_argument("b", help="right")

    args = parser.parse_args()

    diff(args.a, args.b)

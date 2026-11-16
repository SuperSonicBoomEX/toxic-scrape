"""Collect X posts and replies for our 6 topics.

How to run (inside this folder):
    python collect_x.py login                                              # save your X cookies once
    python collect_x.py collect --since 2026-11-09 --until 2026-11-16 --dry-run   # see the searches only
    python collect_x.py collect --since 2026-11-09 --until 2026-11-16      # real run
    python collect_x.py summary --out-dir data/raw                         # check + make combined.csv

If X rate-limits the account, wait 15 minutes and run the same command again.
Finished files are skipped, so it continues where it stopped.
"""
import argparse
import asyncio
import csv
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB = Path.home() / ".twscrape_kmutt" / "accounts.db"

TOPICS = {
    "us_politics": ["uspolitics", "republicans", "democrats"],
    "kpop": ["bts", "blackpink", "kpop"],
    "movies": ["movies", "film", "netflix"],
    "tech": ["ai", "tech", "iphone"],
    "pets": ["pets", "catlovers", "doglovers"],
    "food": ["recipe", "cooking", "foodie"],
}
LEVEL = {"us_politics": "high", "kpop": "high", "movies": "mid",
         "tech": "mid", "pets": "low", "food": "low"}

# We don't save usernames or links, to protect people's privacy.
COLUMNS = [
    "topic", "level", "hashtag", "type", "tweet_id", "parent_id", "text",
    "created_at", "lang", "like_count", "reply_count", "retweet_count", "parent_text",
]


def utc_ts(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def posts_query(tag, since, until):
    # We use since_time/until_time instead of since:/until: because X reads
    # since:/until: in the account's time zone, and our day windows overlapped.
    # -filter:replies keeps posts and replies apart, so we can compare them.
    return (f"#{tag} lang:en -filter:retweets -filter:replies "
            f"since_time:{utc_ts(since)} until_time:{utc_ts(until)}")


def parents_query(tag, since, until, min_replies):
    return f"{posts_query(tag, since, until)} min_replies:{min_replies}"


def post_row(topic, tag, t):
    return [topic, LEVEL[topic], tag, "post", t.id_str, "", t.rawContent,
            t.date.isoformat(), t.lang, t.likeCount, t.replyCount, t.retweetCount, ""]


def reply_row(topic, tag, post, r):
    return [topic, LEVEL[topic], tag, "reply", r.id_str, post.id_str, r.rawContent,
            r.date.isoformat(), r.lang, r.likeCount, r.replyCount, r.retweetCount,
            post.rawContent]


class open_part:
    # Write to a .part file and rename it to .csv only when the job is finished.
    # Then a stopped run can be started again and it skips the finished files.

    def __init__(self, path):
        self.path = path
        self.part = path.with_suffix(".part")

    def __enter__(self):
        self.f = open(self.part, "w", newline="", encoding="utf-8")
        w = csv.writer(self.f)
        w.writerow(COLUMNS)
        return w, self.f

    def __exit__(self, exc_type, exc, tb):
        self.f.close()
        if exc_type is None:
            os.replace(self.part, self.path)
        return False


def day_windows(since, until):
    start, end = date.fromisoformat(since), date.fromisoformat(until)
    days = []
    while start < end:
        days.append((start.isoformat(), (start + timedelta(days=1)).isoformat()))
        start += timedelta(days=1)
    return days


async def search_per_day(api, args, make_query, total):
    # X search gives the newest tweets first, so one search for the whole week
    # only reached the last 1-2 days (we saw this in the small test run).
    # So we search each day separately and take the same number from each day.
    days = day_windows(args.since, args.until)
    per_day = math.ceil(total / len(days))
    found, seen = [], set()
    for d_since, d_until in days:
        if len(found) >= total:
            break
        got = [t async for t in api.search(make_query(d_since, d_until), limit=per_day)][:per_day]
        new = [t for t in got if t.id not in seen]
        seen.update(t.id for t in new)
        print(f"    {d_since}: {len(new)} of {per_day}")
        found.extend(new)
    return found


async def run_posts(api, topic, tag, args, path):
    posts = await search_per_day(api, args, lambda s, u: posts_query(tag, s, u),
                                 args.posts_per_tag)
    with open_part(path) as (writer, f):
        for t in posts:
            writer.writerow(post_row(topic, tag, t))
    return len(posts)


async def run_replies(api, topic, tag, args, path):
    # Several parent posts per hashtag, so one long thread can't dominate a topic.
    parents = await search_per_day(
        api, args, lambda s, u: parents_query(tag, s, u, args.min_replies), args.reply_posts)
    print(f"  found {len(parents)} parent posts")
    total = 0
    with open_part(path) as (writer, f):
        for post in parents:
            kept = 0
            # Ask for more than we need: some results are replies to other replies
            # (a different conversation) or not English, and we skip those.
            async for r in api.tweet_replies(post.id, limit=args.per_post * 3):
                if r.inReplyToTweetId == post.id and r.id != post.id and r.lang == "en":
                    writer.writerow(reply_row(topic, tag, post, r))
                    f.flush()
                    kept += 1
                    if kept >= args.per_post:
                        break
            print(f"    post {post.id}: kept {kept} replies")
            total += kept
    return total


async def setup_account(api, db_path):
    cookies, username = os.environ.get("X_COOKIES"), os.environ.get("X_USERNAME")
    if cookies and username:
        await api.pool.add_account_cookies(username, cookies)
    elif cookies or username:
        sys.exit("Set both X_COOKIES and X_USERNAME, or neither.")
    accounts = await api.pool.accounts_info()
    if not any(a["active"] for a in accounts):
        sys.exit(f"No active X account in {db_path}. Run `python collect_x.py login` first.")


async def collect(args):
    kinds = ["post", "reply"] if args.type == "both" else [args.type]
    jobs = [(topic, tag, kind)
            for topic, tags in TOPICS.items()
            if not args.topics or topic in args.topics
            for tag in tags
            for kind in kinds]
    out = Path(args.out_dir)

    if args.dry_run:
        for topic, tag, kind in jobs:
            q = (posts_query(tag, args.since, args.until) if kind == "post"
                 else parents_query(tag, args.since, args.until, args.min_replies))
            print(f"[{topic}] {kind}: {q}")
        print(f"\n{len(jobs)} jobs. Nothing was sent to X.")
        return

    from twscrape import API
    from twscrape.accounts_pool import NoAccountError

    out.mkdir(parents=True, exist_ok=True)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    api = API(str(args.db), raise_when_no_account=True, wait_timeout=args.wait)
    await setup_account(api, args.db)

    for i, (topic, tag, kind) in enumerate(jobs, 1):
        path = out / f"{topic}__{tag}__{kind}.csv"
        if path.exists():
            print(f"[{i}/{len(jobs)}] already done: {path.name}")
            continue
        print(f"[{i}/{len(jobs)}] {topic} #{tag} {kind}")
        try:
            if kind == "post":
                n = await run_posts(api, topic, tag, args, path)
            else:
                n = await run_replies(api, topic, tag, args, path)
            print(f"  saved {n} rows -> {path.name}")
        except NoAccountError:
            print(f"\nSTOPPED: the account is rate-limited (waited {args.wait}s).")
            print("Wait 15 minutes and run the same command again.")
            sys.exit(1)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e} (it will try again next run)")

    print(f"\nDone. Next: python collect_x.py summary --out-dir {args.out_dir}")


def summary(args):
    import pandas as pd

    out = Path(args.out_dir)
    files = sorted(out.glob("*__*__*.csv"))
    if not files:
        sys.exit(f"No collected files in {out}")
    df = pd.concat([pd.read_csv(p, dtype={"tweet_id": str, "parent_id": str}) for p in files],
                   ignore_index=True)
    df["text"] = df["text"].fillna("")

    rows = []
    for (topic, tag, kind), g in df.groupby(["topic", "hashtag", "type"], sort=False):
        rows.append({
            "topic": topic, "hashtag": "#" + tag, "type": kind, "rows": len(g),
            "parents": g["parent_id"].nunique() if kind == "reply" else "",
            "dup_text_%": round(100 * g["text"].str.strip().str.lower().duplicated().mean()),
            "short_<3w_%": round(100 * (g["text"].str.split().str.len() < 3).mean()),
            "has_link_%": round(100 * g["text"].str.contains(r"https?://", regex=True).mean()),
            "date_min": g["created_at"].min()[:10],
            "date_max": g["created_at"].max()[:10],
        })
    table = pd.DataFrame(rows)
    print("\nPER HASHTAG\n" + table.to_string(index=False))

    # We put posts and replies in one file so the notebook has one table to read.
    # The `type` column keeps them apart.
    # One tweet can have two hashtags of the same topic (#bts and #kpop), so we keep it once.
    # A tweet found in two different topics can't be counted fairly in either, so we drop it.
    before = len(df)
    df = df.drop_duplicates(subset=["topic", "type", "tweet_id"])
    in_topics = df.groupby("tweet_id")["topic"].transform("nunique")
    cross = int((in_topics > 1).sum())
    df = df[in_topics == 1]
    print(f"\nMerged: {before} rows -> {len(df)} "
          f"({before - len(df) - cross} same-topic duplicates, {cross} rows in 2+ topics dropped)")

    counts = df.pivot_table(index="topic", columns="type", values="tweet_id",
                            aggfunc="count", fill_value=0)
    print("\nPER TOPIC\n" + counts.to_string())

    df[COLUMNS].to_csv(out / "combined.csv", index=False, encoding="utf-8")
    table.to_csv(out / "summary_per_hashtag.csv", index=False, encoding="utf-8")

    # 20 random tweets per hashtag for a quick manual spam check in Excel.
    sample = pd.concat([g.sample(min(len(g), 20), random_state=42)
                        for _, g in df.groupby(["hashtag", "type"])])
    sample = sample[["topic", "hashtag", "type", "tweet_id", "text"]].assign(is_spam_or_ad="")
    sample.to_csv(out / "spam_check.csv", index=False, encoding="utf-8-sig")

    print(f"\nSaved {out / 'combined.csv'}, summary_per_hashtag.csv and spam_check.csv")


async def login(args):
    from twscrape import API

    username, cookies = os.environ.get("X_USERNAME"), os.environ.get("X_COOKIES")
    if not (username and cookies):
        sys.exit("Set X_COOKIES and X_USERNAME in this terminal first.")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    api = API(str(args.db))
    try:
        await api.pool.add_account_cookies(username, cookies)
    except ValueError as e:
        sys.exit(f"Bad X_COOKIES: {e}")
    print(f"Saved cookies for {username}.\n\nSaved accounts:")
    for a in await api.pool.accounts_info():
        print(f"  {a['username']}: active={a['active']}")


def main():
    sys.stdout.reconfigure(errors="replace")  # Windows terminals can crash on emoji
    p = argparse.ArgumentParser(description="Collect X data for the toxicity project.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="collect posts and replies")
    c.add_argument("--since", required=True, help="start date YYYY-MM-DD")
    c.add_argument("--until", required=True, help="end date YYYY-MM-DD (not included)")
    c.add_argument("--out-dir", default="data/raw")
    c.add_argument("--type", choices=["post", "reply", "both"], default="both")
    c.add_argument("--topics", nargs="*", choices=list(TOPICS), help="only these topics")
    c.add_argument("--posts-per-tag", type=int, default=105, help="posts per hashtag (15 a day)")
    c.add_argument("--reply-posts", type=int, default=7, help="parent posts per hashtag (1 a day)")
    c.add_argument("--per-post", type=int, default=20, help="max replies per parent post")
    # 10, not 20: in the small test run, pets posts almost never had 20 replies.
    c.add_argument("--min-replies", type=int, default=10, help="replies a parent post needs")
    c.add_argument("--wait", type=int, default=900, help="seconds to wait when rate-limited")
    c.add_argument("--db", type=Path, default=DEFAULT_DB)
    c.add_argument("--dry-run", action="store_true", help="print the searches only")

    s = sub.add_parser("summary", help="check the files and make combined.csv")
    s.add_argument("--out-dir", default="data/raw")

    lg = sub.add_parser("login", help="save X_COOKIES and X_USERNAME from this terminal")
    lg.add_argument("--db", type=Path, default=DEFAULT_DB)

    args = p.parse_args()
    if args.cmd == "collect":
        asyncio.run(collect(args))
    elif args.cmd == "login":
        asyncio.run(login(args))
    else:
        summary(args)


if __name__ == "__main__":
    main()

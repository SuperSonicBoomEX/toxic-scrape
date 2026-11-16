# How Toxic Is X (Twitter)? A Topic Comparison

A text analytics final project at KMUTT (group Goon.txt).

We collect posts and replies from X (Twitter) on 6 topics. We score how toxic they are, and compare the topics with what we expected before we saw the data.

## Objectives

1. Measure and compare the level of toxicity across topics on X, and between posts and replies.
2. Find the most common type of toxicity in each topic (insult, obscene, threat, and so on).
3. Compare a simple bad-word list with AI toxicity models (Detoxify and Twitter-RoBERTa) and show what the word list misses.

## How it works

```
 1. Expect          2. Pick           3. Scrape          4. Analyse
 ─────────          ───────           ─────────          ──────────
 Group votes   →    3 hashtags   →    collect_x.py  →    Notebook:
 High/Mid/Low       per topic         posts + replies    Detoxify, RoBERTa,
 per topic                                               bad-word list
```

### Step 1: Expect the toxicity level of each topic

Six members each rated 12 candidate topics as **High**, **Mid** or **Low** expected toxicity, working alone (`../vote_topic.csv`). For each topic we calculated the **% agreement** (the share of members who chose the most common level). It ranged from 67% to 100%.

Then we discussed the results together and chose 2 topics per level. All 6 chosen topics had **100% agreement**. For Low, 4 topics tied at 100%, so we chose the 2 most likely to have real conversations (enough replies).

| Expected level | Topic | Votes (H / M / L) | Agreement |
|---|---|---|---|
| High | US Politics | 6 / 0 / 0 | 100% |
| High | K-pop Fandoms | 6 / 0 / 0 | 100% |
| Mid | Movies & TV | 0 / 6 / 0 | 100% |
| Mid | Tech & AI | 0 / 6 / 0 | 100% |
| Low | Pets & Animals | 0 / 0 / 6 | 100% |
| Low | Food & Cooking | 0 / 0 / 6 | 100% |

Later, we compare this guess with the measured result.

### Step 2: Pick hashtags

We use 3 neutral hashtags per topic. We avoid hashtags about one person, one company or one news event (for example `#musk`), because they pull in tweets from other topics and bias the result.

| Expected level | Topic | Hashtags |
|---|---|---|
| High | US Politics | #uspolitics #Republicans #Democrats |
| High | K-pop Fandoms | #bts #blackpink #kpop |
| Mid | Movies | #movies #film #netflix |
| Mid | Tech | #AI #tech #iphone |
| Low | Pets & Animals | #pets #catlovers #doglovers |
| Low | Food & Cooking | #recipe #cooking #foodie |

### Step 3: Scrape the data with `collect_x.py`

For each hashtag, the script collects:

- **Posts**: original tweets with the hashtag (no retweets, no replies)
- **Replies**: direct English replies under posts that have at least 10 replies

All topics use the **same date window**, and tweets are collected **evenly from each day** of the window. (X search returns the newest tweets first, so one search for the whole week would only reach the last 1–2 days.)

### Step 4: Analyse in a notebook (planned)

| Step | Method | Output |
|---|---|---|
| Clean | Remove links, @mentions, duplicates and very short tweets | Clean dataset |
| Bad-word list | Match each tweet against the LDNOOBW English list (token and regex matching, no training) | `bw_toxic` (0/1) |
| Detoxify `unbiased` | AI model trained on Jigsaw comments | Toxicity score + 7 types |
| Twitter-RoBERTa offensive | `cardiffnlp/twitter-roberta-base-offensive`, trained on tweets | Offensive score |
| Hand labels | 200–300 random tweets labelled by 2 members each | Ground truth for Objective 3 |
| Compare | % toxic per topic and type, ranking vs. the group's guess, precision/recall/F1 per method | Figures and tables |
| Extra | LDA topic modelling on toxic tweets | What toxic tweets talk about |

## Project status

| Step | Status |
|---|---|
| Test X data collection (`test_twscrape.py`) | Done |
| Vote on topics and expected levels | Done (% agreement + group discussion) |
| Pick hashtags | Done |
| Pilot scrape (small run to check the hashtags) | Done |
| Full scrape | Next |
| Clean, score and analyse (notebook) | Not started |
| Report and slides | Not started |

## Run the scraper

You need Python and an X account. Use a dedicated account, because X can restrict accounts that scrape.

**1. Install**

```powershell
pip install twscrape pandas
```

**2. Add your login (first run only)**

Log in to x.com, then copy `auth_token` and `ct0` from your browser's DevTools (Application > Cookies > `https://x.com`). Set them in the same PowerShell window you use to run the script:

```powershell
$env:X_COOKIES = "auth_token=PASTE_HERE; ct0=PASTE_HERE"
$env:X_USERNAME = "your_x_handle_without_the_at_sign"
python collect_x.py login
```

`login` saves the cookies to `~/.twscrape_kmutt/accounts.db` (outside this repo) and lists the saved accounts. With 2 accounts, set the variables and run `login` once for each. More accounts means shorter rate-limit waits.

**Never paste real cookie values into a file**, including this README and the comments in `collect_x.py`. Type them only in the terminal.

**3. Check the queries (nothing is sent to X)**

```powershell
python collect_x.py collect --since 2026-11-09 --until 2026-11-16 --dry-run
```

**4. Pilot run (small)**

```powershell
python collect_x.py collect --since 2026-11-09 --until 2026-11-16 --out-dir data/pilot --posts-per-tag 49 --reply-posts 1
python collect_x.py summary --out-dir data/pilot
```

Check the summary table, then open `data/pilot/spam_check.csv` and mark spam or ads with `1`. Replace any hashtag that has too few tweets or too much spam.

**5. Full run (use the same dates as the pilot)**

```powershell
python collect_x.py collect --since 2026-11-09 --until 2026-11-16
python collect_x.py summary --out-dir data/raw
```

The result is `data/raw/combined.csv`, which is the input for the notebook.

`--until` is exclusive, so `2026-11-16` includes tweets from 15 November.

### Waiting for rate limits

X limits how many requests one account can make, usually per **15-minute** window.

- When the limit is hit, the script **waits up to 15 minutes** (`--wait 900`) and then continues.
- If the account is still blocked after that, the script stops. **Wait 15 minutes or more and run the same command again.** Finished files are kept and skipped, so it continues where it stopped.
- With one account, the full run can take **from about 30 minutes to a few hours**, depending on X's limits. Start early.

### Options for `collect`

| Option | Default | Meaning |
|---|---|---|
| `--since` / `--until` | required | Date window (YYYY-MM-DD), `until` is exclusive |
| `--out-dir` | `data/raw` | Output folder |
| `--type` | `both` | `post`, `reply` or `both` |
| `--topics` | all | Only these topics, e.g. `--topics kpop tech` |
| `--posts-per-tag` | `105` | Posts per hashtag, spread evenly over the days (15 per day for 7 days) |
| `--reply-posts` | `7` | Parent posts per hashtag, spread over the days (1 per day) |
| `--per-post` | `20` | Maximum replies per parent post |
| `--min-replies` | `10` | Minimum replies a parent post needs |
| `--wait` | `900` | Seconds to wait when rate-limited |
| `--dry-run` | off | Print the queries only |

### Output columns

`topic, level, hashtag, type, tweet_id, parent_id, text, created_at, lang, like_count, reply_count, retweet_count, parent_text`

Usernames and URLs are not saved. A tweet can still be found with `x.com/i/status/<tweet_id>`.

**Duplicates:** a tweet found under two hashtags of the same topic (for example #bts and #kpop) is kept once. A tweet that falls in two different topics is dropped from both.

## Files

| File | Purpose |
|---|---|
| `collect_x.py` | Main scraper: collects posts and replies for all topics, and summarises the results |
| `test_twscrape.py` | Earlier test script for one hashtag (kept for reference) |
| `data/pilot/` | Pilot run output |
| `data/raw/` | Full run output, including `combined.csv` |
| `../vote_topic.csv` | The group's topic votes |

The `data/` folders are not committed to Git.

## Important notes

- **Keep cookies private.** They give full access to the account. Never put them in a script, this README, a notebook or a Git commit. Set them only in the terminal.
- **Protect the data.** Don't show tweet IDs or usernames in the report or slides.
- **Know the risks.** twscrape uses X's private API, and scraping without written consent breaks X's terms. The account can be blocked, and the tool can stop working if X changes its API. We will disclose this method in the report.
- **Collect slowly.** Run the pilot first, and don't run several scrapes at the same time on one account.

## Limitations to report

- One platform only (X), English only, and one date window (just after the 2026 US midterm elections).
- Hashtag sampling: tweets with hashtags may not represent all tweets on a topic.
- K-pop uses the two largest fandoms, which may have more fan conflict than smaller fandoms.
- The AI models were trained on other data (Jigsaw comments, older tweets), and they see a reply without its full conversation.

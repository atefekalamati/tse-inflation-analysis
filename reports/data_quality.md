# Data quality report (raw data, step 1)

Generated 2026-10-13T12:54:21-07:00 by `src/data_quality.py`. Raw data downloaded 2026-10-13T23:13:14+03:30 (Tehran time) with algotik-tse 1.8.0. Nothing in data/raw was modified.

Analysis period 1402-07-01 to 1405-06-31 (Jalali). Prices were fetched from 1402-06-01 so the base price at the end of 1402-06 exists.

Index calendar = days on which شاخص کل has a row: 739 days in the fetch window, 720 in the analysis period. Of these, 61 rows have zero market volume and a flat index (market closed). Days the market was open: 678 in the fetch window, 659 in the analysis period.

Price conventions: `Close` = last trade, `Final` = official closing price (قیمت پایانی). Returns below use adjusted `Final` (and `Close` where noted). Adjusted series are back-adjusted by the library within the download window and truncated to integers.

## Summary

`suspended (period)` counts open-market days in the analysis period on which the symbol did not trade. Market-wide closures are excluded.

| series | first | last | rows | days in period | dup | suspended (period) | |ret|>10% | adj. events |
|---|---|---|---|---|---|---|---|---|
| فولاد | 1402-06-01 | 1405-06-31 | 600 | 581 | 0 | 78 | 0 | 5 |
| فملی | 1402-06-01 | 1405-06-31 | 630 | 611 | 0 | 48 | 0 | 5 |
| شپنا | 1402-06-01 | 1405-06-31 | 655 | 636 | 0 | 23 | 0 | 6 |
| خودرو | 1402-06-01 | 1405-06-31 | 601 | 582 | 0 | 77 | 2 | 1 |
| وبملت | 1402-06-01 | 1405-06-31 | 648 | 629 | 0 | 30 | 2 | 6 |
| اخابر | 1402-06-01 | 1405-06-31 | 625 | 607 | 0 | 52 | 1 | 4 |
| شستا | 1402-06-01 | 1405-06-31 | 667 | 648 | 0 | 11 | 0 | 3 |
| تیپیکو | 1402-06-01 | 1405-06-31 | 656 | 641 | 0 | 18 | 0 | 5 |
| شاخص کل | 1402-06-01 | 1405-06-31 | 739 | 720 | 0 | 0 | 0 |  |
| شاخص کل (هم وزن) | 1402-06-01 | 1405-06-31 | 739 | 720 | 0 | 0 | 0 |  |
| فلزات اساسی | 1402-06-01 | 1405-06-31 | 739 | 720 | 0 | 0 | 0 |  |
| فرآورده‌های نفتی | 1402-06-01 | 1405-06-31 | 739 | 720 | 0 | 0 | 10 |  |
| خودرو و ساخت قطعات | 1402-06-01 | 1405-06-31 | 739 | 720 | 0 | 0 | 2 |  |
| بانک‌ها و موسسات اعتباری | 1402-06-01 | 1405-06-31 | 739 | 720 | 0 | 0 | 0 |  |
| مخابرات | 1402-06-01 | 1405-06-31 | 739 | 720 | 0 | 0 | 1 |  |
| سرمایه‌گذاری‌ها | 1402-06-01 | 1405-06-31 | 739 | 720 | 0 | 0 | 0 |  |
| مواد و محصولات دارویی | 1402-06-01 | 1405-06-31 | 739 | 720 | 0 | 0 | 0 |  |


## Flags to review

- `data/raw/stock_shasta_adjusted.csv`: `Open` <= 0 on 1 day(s): 1402-07-17
- `data/raw/stock_shasta_unadjusted.csv`: `Open` <= 0 on 1 day(s): 1402-07-17
- `data/raw/index_equal_weight.csv`: `Open` outside the day's Low-High range on 2 day(s): 1404-09-19, 1404-11-12
- `data/raw/index_equal_weight.csv`: `Close` outside the day's Low-High range on 2 day(s): 1404-09-19, 1404-11-12
- `data/raw/sector_of_shepna.csv`: `Close` outside the day's Low-High range on 3 day(s): 1404-12-11, 1404-12-12, 1404-12-13
- خودرو: 2 day(s) with |adjusted return| > 10%: 1404-02-02 +37.80% (first trade after 19 open-market days without trading; ex-date of an adjustment event); 1404-05-08 -26.18% (first trade after 23 open-market days without trading)
- وبملت: 2 day(s) with |adjusted return| > 10%: 1404-05-14 -13.03% (first trade after 11 open-market days without trading; ex-date of an adjustment event); 1405-05-04 +12.13% (first trade after 3 open-market days without trading; ex-date of an adjustment event)
- اخابر: 1 day(s) with |adjusted return| > 10%: 1404-02-07 +24.89% (first trade after 22 open-market days without trading; ex-date of an adjustment event)
- شاخص کل (هم وزن) (`data/raw/index_equal_weight.csv`): decimal-shift errors in the source data: `Open` 1404-09-19 (x10), 1404-11-12 (x10); `Low` 1404-09-19 (x10), 1404-11-12 (x10). `Close` is not affected.
- فرآورده‌های نفتی (`data/raw/sector_of_shepna.csv`): decimal-shift errors in the source data: `High` 1404-03-19 (x0.1), 1404-03-28 (x0.1), 1404-04-01 (x0.1), 1404-04-03 (x0.1), 1404-04-07 (x0.1); `Low` 1404-03-19 (x0.1), 1404-03-28 (x0.1), 1404-04-01 (x0.1), 1404-04-03 (x0.1), 1404-04-07 (x0.1); `Close` 1404-03-19 (x0.1), 1404-03-28 (x0.1), 1404-04-01 (x0.1), 1404-04-03 (x0.1), 1404-04-07 (x0.1). The `Close` errors cause the -90% / +900% daily returns and must be repaired or masked before analysis.
- خودرو و ساخت قطعات: 2 daily move(s) > 10%: 1404-02-02 +15.73%, 1404-05-08 -13.93%.
- مخابرات: 1 daily move(s) > 10%: 1404-02-07 +13.29%.


## Informational notes

- `data/raw/stock_foolad_adjusted.csv`: `Final` outside the day's Low-High on 2 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_foolad_unadjusted.csv`: `Final` outside the day's Low-High on 2 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_fameli_adjusted.csv`: `Final` outside the day's Low-High on 2 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_fameli_unadjusted.csv`: `Final` outside the day's Low-High on 2 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_shepna_adjusted.csv`: `Final` outside the day's Low-High on 17 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_shepna_unadjusted.csv`: `Final` outside the day's Low-High on 17 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_khodro_adjusted.csv`: `Final` outside the day's Low-High on 16 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_khodro_unadjusted.csv`: `Final` outside the day's Low-High on 18 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_vbmellat_adjusted.csv`: `Final` outside the day's Low-High on 3 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_vbmellat_unadjusted.csv`: `Final` outside the day's Low-High on 4 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_akhaber_adjusted.csv`: `Final` outside the day's Low-High on 61 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_akhaber_unadjusted.csv`: `Final` outside the day's Low-High on 63 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_shasta_adjusted.csv`: `Final` outside the day's Low-High on 12 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_shasta_unadjusted.csv`: `Final` outside the day's Low-High on 12 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_tipico_adjusted.csv`: `Final` outside the day's Low-High on 78 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/stock_tipico_unadjusted.csv`: `Final` outside the day's Low-High on 78 day(s). TSETMC's closing price is a volume-weighted figure and can sit outside the traded range; not treated as an error.
- `data/raw/index_total.csv`: `Open` = 0 on 60 day(s), all of them market-closed days. Expected, because nothing traded; `Close` is the carried-forward value.
- `data/raw/index_equal_weight.csv`: `Open` = 0 on 60 day(s), all of them market-closed days. Expected, because nothing traded; `Close` is the carried-forward value.
- `data/raw/sector_of_shepna.csv`: `High` = 0 on 3 day(s), all of them market-closed days. Expected, because nothing traded; `Close` is the carried-forward value.
- `data/raw/sector_of_shepna.csv`: `Low` = 0 on 3 day(s), all of them market-closed days. Expected, because nothing traded; `Close` is the carried-forward value.
- فولاد: 3 adjustment event(s) are absent or only partly present in TSETMC's price-adjustment table. The library's adjusted prices still include them, because it derives factors from the previous-day price TSETMC publishes.
- فملی: 3 adjustment event(s) are absent or only partly present in TSETMC's price-adjustment table. The library's adjusted prices still include them, because it derives factors from the previous-day price TSETMC publishes.
- شپنا: 3 adjustment event(s) are absent or only partly present in TSETMC's price-adjustment table. The library's adjusted prices still include them, because it derives factors from the previous-day price TSETMC publishes.
- خودرو: 1 adjustment event(s) are absent or only partly present in TSETMC's price-adjustment table. The library's adjusted prices still include them, because it derives factors from the previous-day price TSETMC publishes.
- وبملت: 4 adjustment event(s) are absent or only partly present in TSETMC's price-adjustment table. The library's adjusted prices still include them, because it derives factors from the previous-day price TSETMC publishes.
- اخابر: 1 adjustment event(s) are absent or only partly present in TSETMC's price-adjustment table. The library's adjusted prices still include them, because it derives factors from the previous-day price TSETMC publishes.
- تیپیکو: 1 adjustment event(s) are absent or only partly present in TSETMC's price-adjustment table. The library's adjusted prices still include them, because it derives factors from the previous-day price TSETMC publishes.
- The equal-weight index file carries the same `Volume` column as شاخص کل (whole-market volume), not a volume of its own.


## Market-wide closures

Index rows with zero market volume (61 days). Stock rows on these days across all 8 symbols: 0. The rows stay in the raw index files and are excluded when counting suspensions.

| from | to | index rows | index Close moved? |
|---|---|---|---|
| 1403-02-31 | 1403-02-31 | 1 | no (flat) |
| 1403-05-17 | 1403-05-17 | 1 | no (flat) |
| 1403-11-20 | 1403-11-20 | 1 | no (flat) |
| 1404-03-25 | 1404-04-04 | 8 | no (flat) |
| 1404-12-09 | 1405-02-28 | 50 | no (flat) |


## Name resolution

- `شاخص کل (هم وزن)` had no exact match. Library search found ['شاخص كل (هم وزن)', 'شاخص كل', 'شاخص قيمت (هم وزن)', 'شاخص صنعت']. Used `شاخص هم وزن` (InsCode 67130298613737946, `شاخص هم وزن`).
- `بانک‌ها و موسسات اعتباری` had no exact match. Library search found ['بانکها']. Used `بانکها` (InsCode 72002976013856737, `Banking`).
- `سرمایه‌گذاری‌ها` had no exact match. Library search found ['سرمایه گذاریها', 'سرمایه گذاری']. Used `سرمایه گذاریها` (InsCode 34295935482222451, `Investment Companies`).
- `مواد و محصولات دارویی` had no exact match. Library search found ['مواد دارویی', 'دارویی', 'محصولات چرمی', 'محصولات چوبی']. Used `مواد دارویی` (InsCode 3615666621538524, `Pharmaceutical`).
- `مخابرات` matched exactly the industry index with InsCode 41867092385281437, which TSETMC's industry list labels `رادیویی` (English: Telecommunications).


## Stocks

### فولاد

Files: `data/raw/stock_foolad_adjusted.csv`, `data/raw/stock_foolad_unadjusted.csv`, `data/raw/adjustments_foolad.csv`

- Range 1402-06-01 to 1405-06-31. 600 rows in the fetch window, 581 trading days in the analysis period (market open on 659 days).
- Adjusted and unadjusted files have identical dates: yes. Duplicate dates: 0. Zero-volume rows: 0.
- Adjusted/unadjusted Final on the last day: 1.0000 (1 expected: the adjustment is anchored at the last date).
- Index days without a trade: 139 (139 in the analysis period). Of these, 61 are market-wide closures and **78 are symbol-specific suspensions** (78 in the analysis period).

  Suspension runs (market-closure days excluded):

  | suspended from | to | open-market days |
  |---|---|---|
  | 1402-07-25 | 1402-07-25 | 1 |
  | 1402-11-18 | 1402-11-23 | 3 |
  | 1402-12-01 | 1402-12-08 | 5 |
  | 1403-04-27 | 1403-04-31 | 3 |
  | 1403-07-18 | 1403-07-18 | 1 |
  | 1403-08-20 | 1403-08-20 | 1 |
  | 1403-12-18 | 1403-12-21 | 4 |
  | 1404-01-05 | 1404-01-06 | 2 |
  | 1404-04-22 | 1404-04-23 | 2 |
  | 1404-05-12 | 1404-05-14 | 3 |
  | 1404-11-18 | 1404-11-19 | 2 |
  | 1405-02-29 | 1405-05-14 | 51 |


- Adjustment events, where adjusted and unadjusted Final diverge: 5. `factor` multiplies all prices before the ex-date.

| last trade before | ex-date | factor | equiv. gap | raw Final before / on ex-date | TSETMC table date (ratio) | note |
|---|---|---|---|---|---|---|
| 1402-11-30 | 1402-12-09 | 0.7405 | -25.95% | 5930 / 4466 |  | not in TSETMC table (likely capital increase) |
| 1403-04-24 | 1403-05-01 | 0.9233 | -7.67% | 5200 / 4738 | 1403-04-31 (0.9231) | matches TSETMC table (dividend) |
| 1403-12-15 | 1403-12-22 | 0.7201 | -27.99% | 5530 / 3922 |  | not in TSETMC table (likely capital increase) |
| 1404-05-11 | 1404-05-15 | 0.9017 | -9.83% | 2860 / 2430 | 1404-05-13 (0.9021) | matches TSETMC table (dividend) |
| 1404-12-06 | 1405-05-17 | 0.7589 | -24.11% | 3359 / 2332 | 1405-05-12 (0.9789) | TSETMC table explains -2.11%; remaining -22.48% unlisted (likely capital increase) |


- Days with |adjusted daily return| > 10% (Final or Close): 0

_none_


### فملی

Files: `data/raw/stock_fameli_adjusted.csv`, `data/raw/stock_fameli_unadjusted.csv`, `data/raw/adjustments_fameli.csv`

- Range 1402-06-01 to 1405-06-31. 630 rows in the fetch window, 611 trading days in the analysis period (market open on 659 days).
- Adjusted and unadjusted files have identical dates: yes. Duplicate dates: 0. Zero-volume rows: 0.
- Adjusted/unadjusted Final on the last day: 1.0000 (1 expected: the adjustment is anchored at the last date).
- Index days without a trade: 109 (109 in the analysis period). Of these, 61 are market-wide closures and **48 are symbol-specific suspensions** (48 in the analysis period).

  Suspension runs (market-closure days excluded):

  | suspended from | to | open-market days |
  |---|---|---|
  | 1402-11-23 | 1402-12-08 | 11 |
  | 1402-12-12 | 1402-12-12 | 1 |
  | 1403-04-30 | 1403-05-02 | 4 |
  | 1403-10-22 | 1403-10-22 | 1 |
  | 1404-01-27 | 1404-02-21 | 18 |
  | 1404-04-09 | 1404-04-09 | 1 |
  | 1404-04-30 | 1404-05-05 | 5 |
  | 1405-04-30 | 1405-05-07 | 7 |


- Adjustment events, where adjusted and unadjusted Final diverge: 5. `factor` multiplies all prices before the ex-date.

| last trade before | ex-date | factor | equiv. gap | raw Final before / on ex-date | TSETMC table date (ratio) | note |
|---|---|---|---|---|---|---|
| 1402-11-21 | 1402-12-09 | 0.7696 | -23.04% | 7290 / 5600 |  | not in TSETMC table (likely capital increase) |
| 1403-04-27 | 1403-05-03 | 0.9519 | -4.81% | 7690 / 7180 | 1403-05-01 (0.9519) | matches TSETMC table (dividend) |
| 1404-01-26 | 1404-02-22 | 0.7428 | -25.72% | 9720 / 7490 |  | not in TSETMC table (likely capital increase) |
| 1404-04-29 | 1404-05-06 | 0.9453 | -5.47% | 6750 / 6190 | 1404-05-01 (0.9452) | matches TSETMC table (dividend) |
| 1405-04-29 | 1405-05-10 | 0.7132 | -28.68% | 20470 / 14860 | 1405-05-03 (0.9780) | TSETMC table explains -2.20%; remaining -27.07% unlisted (likely capital increase) |


- Days with |adjusted daily return| > 10% (Final or Close): 0

_none_


### شپنا

Files: `data/raw/stock_shepna_adjusted.csv`, `data/raw/stock_shepna_unadjusted.csv`, `data/raw/adjustments_shepna.csv`

- Range 1402-06-01 to 1405-06-31. 655 rows in the fetch window, 636 trading days in the analysis period (market open on 659 days).
- Adjusted and unadjusted files have identical dates: yes. Duplicate dates: 0. Zero-volume rows: 0.
- Adjusted/unadjusted Final on the last day: 1.0000 (1 expected: the adjustment is anchored at the last date).
- Index days without a trade: 84 (84 in the analysis period). Of these, 61 are market-wide closures and **23 are symbol-specific suspensions** (23 in the analysis period).

  Suspension runs (market-closure days excluded):

  | suspended from | to | open-market days |
  |---|---|---|
  | 1402-10-30 | 1402-11-02 | 3 |
  | 1402-11-30 | 1402-12-07 | 5 |
  | 1403-02-30 | 1403-03-01 | 2 |
  | 1403-04-27 | 1403-04-30 | 2 |
  | 1403-12-25 | 1403-12-28 | 4 |
  | 1404-04-29 | 1404-04-31 | 3 |
  | 1405-04-10 | 1405-04-10 | 1 |
  | 1405-04-29 | 1405-04-31 | 3 |


- Adjustment events, where adjusted and unadjusted Final diverge: 6. `factor` multiplies all prices before the ex-date.

| last trade before | ex-date | factor | equiv. gap | raw Final before / on ex-date | TSETMC table date (ratio) | note |
|---|---|---|---|---|---|---|
| 1402-11-29 | 1402-12-08 | 0.6120 | -38.80% | 7700 / 4681 |  | not in TSETMC table (likely capital increase) |
| 1403-04-24 | 1403-04-31 | 0.8908 | -10.92% | 5600 / 4561 | 1403-04-30 (0.8911) | matches TSETMC table (dividend) |
| 1403-12-22 | 1404-01-05 | 0.7043 | -29.57% | 4880 / 3650 |  | not in TSETMC table (likely capital increase) |
| 1404-04-28 | 1404-05-01 | 0.9055 | -9.45% | 3810 / 3558 | 1404-04-30 (0.9055) | matches TSETMC table (dividend) |
| 1404-12-06 | 1405-02-29 | 0.8401 | -15.99% | 6130 / 5030 |  | not in TSETMC table (likely capital increase) |
| 1405-04-28 | 1405-05-03 | 0.9253 | -7.47% | 9900 / 10040 | 1405-04-30 (0.9253) | matches TSETMC table (dividend) |


- Days with |adjusted daily return| > 10% (Final or Close): 0

_none_


### خودرو

Files: `data/raw/stock_khodro_adjusted.csv`, `data/raw/stock_khodro_unadjusted.csv`, `data/raw/adjustments_khodro.csv`

- Range 1402-06-01 to 1405-06-31. 601 rows in the fetch window, 582 trading days in the analysis period (market open on 659 days).
- Adjusted and unadjusted files have identical dates: yes. Duplicate dates: 0. Zero-volume rows: 0.
- Adjusted/unadjusted Final on the last day: 1.0000 (1 expected: the adjustment is anchored at the last date).
- Index days without a trade: 138 (138 in the analysis period). Of these, 61 are market-wide closures and **77 are symbol-specific suspensions** (77 in the analysis period).

  Suspension runs (market-closure days excluded):

  | suspended from | to | open-market days |
  |---|---|---|
  | 1402-11-16 | 1402-11-28 | 8 |
  | 1403-04-30 | 1403-04-31 | 2 |
  | 1403-08-28 | 1403-08-28 | 1 |
  | 1403-10-19 | 1403-10-19 | 1 |
  | 1403-11-16 | 1403-11-17 | 2 |
  | 1403-12-27 | 1404-02-01 | 19 |
  | 1404-03-21 | 1404-05-07 | 23 |
  | 1404-05-25 | 1404-05-28 | 4 |
  | 1404-07-19 | 1404-07-21 | 3 |
  | 1404-07-27 | 1404-07-27 | 1 |
  | 1404-11-07 | 1404-11-21 | 10 |
  | 1405-03-30 | 1405-03-30 | 1 |
  | 1405-04-30 | 1405-04-31 | 2 |


- Adjustment events, where adjusted and unadjusted Final diverge: 1. `factor` multiplies all prices before the ex-date.

| last trade before | ex-date | factor | equiv. gap | raw Final before / on ex-date | TSETMC table date (ratio) | note |
|---|---|---|---|---|---|---|
| 1403-12-26 | 1404-02-02 | 0.1176 | -88.24% | 3868 / 627 |  | not in TSETMC table (likely capital increase) |


- Days with |adjusted daily return| > 10% (Final or Close): 2

| date | prev. trade | ret Final | ret Close | context |
|---|---|---|---|---|
| 1404-02-02 | 1403-12-26 | +37.80% | +40.53% | first trade after 19 open-market days without trading; ex-date of an adjustment event |
| 1404-05-08 | 1404-03-20 | -26.18% | -28.06% | first trade after 23 open-market days without trading |


### وبملت

Files: `data/raw/stock_vbmellat_adjusted.csv`, `data/raw/stock_vbmellat_unadjusted.csv`, `data/raw/adjustments_vbmellat.csv`

- Range 1402-06-01 to 1405-06-31. 648 rows in the fetch window, 629 trading days in the analysis period (market open on 659 days).
- Adjusted and unadjusted files have identical dates: yes. Duplicate dates: 0. Zero-volume rows: 0.
- Adjusted/unadjusted Final on the last day: 1.0000 (1 expected: the adjustment is anchored at the last date).
- Index days without a trade: 91 (91 in the analysis period). Of these, 61 are market-wide closures and **30 are symbol-specific suspensions** (30 in the analysis period).

  Suspension runs (market-closure days excluded):

  | suspended from | to | open-market days |
  |---|---|---|
  | 1402-10-06 | 1402-10-19 | 10 |
  | 1403-03-29 | 1403-03-30 | 2 |
  | 1403-12-01 | 1403-12-06 | 4 |
  | 1404-04-30 | 1404-05-13 | 11 |
  | 1405-04-30 | 1405-05-03 | 3 |


- Adjustment events, where adjusted and unadjusted Final diverge: 6. `factor` multiplies all prices before the ex-date.

| last trade before | ex-date | factor | equiv. gap | raw Final before / on ex-date | TSETMC table date (ratio) | note |
|---|---|---|---|---|---|---|
| 1402-10-05 | 1402-10-20 | 0.4969 | -50.31% | 4802 / 2488 |  | not in TSETMC table (likely capital increase) |
| 1403-03-27 | 1403-04-02 | 0.9620 | -3.80% | 2258 / 2167 | 1403-03-30 (0.9637) | matches TSETMC table (dividend) |
| 1403-11-30 | 1403-12-07 | 0.5858 | -41.42% | 3048 / 1952 |  | not in TSETMC table (likely capital increase) |
| 1404-04-29 | 1404-05-14 | 0.4901 | -50.99% | 2440 / 1040 | 1404-05-01 (0.9631) | TSETMC table explains -3.69%; remaining -49.12% unlisted (likely capital increase) |
| 1404-12-06 | 1405-02-29 | 0.7032 | -29.68% | 1236 / 914 |  | not in TSETMC table (likely capital increase) |
| 1405-04-29 | 1405-05-04 | 0.9589 | -4.11% | 1118 / 1202 | 1405-04-31 (0.9589) | matches TSETMC table (dividend) |


- Days with |adjusted daily return| > 10% (Final or Close): 2

| date | prev. trade | ret Final | ret Close | context |
|---|---|---|---|---|
| 1404-05-14 | 1404-04-29 | -13.03% | -14.34% | first trade after 11 open-market days without trading; ex-date of an adjustment event |
| 1405-05-04 | 1405-04-29 | +12.13% | +13.34% | first trade after 3 open-market days without trading; ex-date of an adjustment event |


### اخابر

Files: `data/raw/stock_akhaber_adjusted.csv`, `data/raw/stock_akhaber_unadjusted.csv`, `data/raw/adjustments_akhaber.csv`

- Range 1402-06-01 to 1405-06-31. 625 rows in the fetch window, 607 trading days in the analysis period (market open on 659 days).
- Adjusted and unadjusted files have identical dates: yes. Duplicate dates: 0. Zero-volume rows: 0.
- Adjusted/unadjusted Final on the last day: 1.0000 (1 expected: the adjustment is anchored at the last date).
- Index days without a trade: 114 (113 in the analysis period). Of these, 61 are market-wide closures and **53 are symbol-specific suspensions** (52 in the analysis period).

  Suspension runs (market-closure days excluded):

  | suspended from | to | open-market days |
  |---|---|---|
  | 1402-06-14 | 1402-06-14 | 1 |
  | 1402-09-19 | 1402-09-19 | 1 |
  | 1402-10-09 | 1402-10-10 | 2 |
  | 1403-04-27 | 1403-04-31 | 3 |
  | 1403-05-08 | 1403-05-13 | 4 |
  | 1403-10-11 | 1403-10-11 | 1 |
  | 1403-11-28 | 1403-11-29 | 2 |
  | 1403-12-14 | 1403-12-15 | 2 |
  | 1403-12-27 | 1404-02-06 | 22 |
  | 1404-04-11 | 1404-04-18 | 4 |
  | 1404-05-11 | 1404-05-12 | 2 |
  | 1404-07-08 | 1404-07-08 | 1 |
  | 1404-09-12 | 1404-09-12 | 1 |
  | 1405-04-22 | 1405-04-28 | 5 |
  | 1405-05-06 | 1405-05-07 | 2 |


- Adjustment events, where adjusted and unadjusted Final diverge: 4. `factor` multiplies all prices before the ex-date.

| last trade before | ex-date | factor | equiv. gap | raw Final before / on ex-date | TSETMC table date (ratio) | note |
|---|---|---|---|---|---|---|
| 1403-04-24 | 1403-05-01 | 0.9539 | -4.61% | 7600 / 7250 | 1403-04-31 (0.9534) | matches TSETMC table (dividend) |
| 1403-12-26 | 1404-02-07 | 0.0625 | -93.75% | 8480 / 662 |  | not in TSETMC table (likely capital increase) |
| 1404-04-10 | 1404-04-21 | 0.9365 | -6.35% | 628 / 572 | 1404-04-17 (0.9363) | matches TSETMC table (dividend) |
| 1405-04-21 | 1405-04-29 | 0.9322 | -6.78% | 693 / 627 | 1405-04-24 (0.9322) | matches TSETMC table (dividend) |


- Days with |adjusted daily return| > 10% (Final or Close): 1

| date | prev. trade | ret Final | ret Close | context |
|---|---|---|---|---|
| 1404-02-07 | 1403-12-26 | +24.89% | +24.62% | first trade after 22 open-market days without trading; ex-date of an adjustment event |


### شستا

Files: `data/raw/stock_shasta_adjusted.csv`, `data/raw/stock_shasta_unadjusted.csv`, `data/raw/adjustments_shasta.csv`

- Range 1402-06-01 to 1405-06-31. 667 rows in the fetch window, 648 trading days in the analysis period (market open on 659 days).
- Adjusted and unadjusted files have identical dates: yes. Duplicate dates: 0. Zero-volume rows: 0.
- Adjusted/unadjusted Final on the last day: 1.0000 (1 expected: the adjustment is anchored at the last date).
- Index days without a trade: 72 (72 in the analysis period). Of these, 61 are market-wide closures and **11 are symbol-specific suspensions** (11 in the analysis period).

  Suspension runs (market-closure days excluded):

  | suspended from | to | open-market days |
  |---|---|---|
  | 1402-07-26 | 1402-08-02 | 5 |
  | 1403-07-25 | 1403-07-30 | 4 |
  | 1404-07-29 | 1404-07-30 | 2 |


- Adjustment events, where adjusted and unadjusted Final diverge: 3. `factor` multiplies all prices before the ex-date.

| last trade before | ex-date | factor | equiv. gap | raw Final before / on ex-date | TSETMC table date (ratio) | note |
|---|---|---|---|---|---|---|
| 1402-07-25 | 1402-08-03 | 0.8570 | -14.30% | 1319 / 1129 | 1402-07-30 (0.8575) | matches TSETMC table (dividend) |
| 1403-07-24 | 1403-08-01 | 0.8629 | -13.71% | 1091 / 908 | 1403-07-29 (0.8625) | matches TSETMC table (dividend) |
| 1404-07-28 | 1404-08-03 | 0.8678 | -13.22% | 1437 / 1277 | 1404-07-30 (0.8678) | matches TSETMC table (dividend) |


- Days with |adjusted daily return| > 10% (Final or Close): 0

_none_


### تیپیکو

Files: `data/raw/stock_tipico_adjusted.csv`, `data/raw/stock_tipico_unadjusted.csv`, `data/raw/adjustments_tipico.csv`

- Range 1402-06-01 to 1405-06-31. 656 rows in the fetch window, 641 trading days in the analysis period (market open on 659 days).
- Adjusted and unadjusted files have identical dates: yes. Duplicate dates: 0. Zero-volume rows: 0.
- Adjusted/unadjusted Final on the last day: 1.0000 (1 expected: the adjustment is anchored at the last date).
- Index days without a trade: 83 (79 in the analysis period). Of these, 61 are market-wide closures and **22 are symbol-specific suspensions** (18 in the analysis period).

  Suspension runs (market-closure days excluded):

  | suspended from | to | open-market days |
  |---|---|---|
  | 1402-06-18 | 1402-06-21 | 4 |
  | 1403-06-17 | 1403-06-18 | 2 |
  | 1404-06-22 | 1404-06-25 | 4 |
  | 1405-03-20 | 1405-03-23 | 2 |
  | 1405-05-07 | 1405-05-17 | 6 |
  | 1405-06-16 | 1405-06-21 | 4 |


- Adjustment events, where adjusted and unadjusted Final diverge: 5. `factor` multiplies all prices before the ex-date.

| last trade before | ex-date | factor | equiv. gap | raw Final before / on ex-date | TSETMC table date (ratio) | note |
|---|---|---|---|---|---|---|
| 1402-06-14 | 1402-06-22 | 0.8888 | -11.12% | 34740 / 30870 | 1402-06-20 (0.8889) | matches TSETMC table (dividend) |
| 1403-06-13 | 1403-06-19 | 0.8708 | -12.92% | 23240 / 20230 | 1403-06-18 (0.8709) | matches TSETMC table (dividend) |
| 1404-06-18 | 1404-06-26 | 0.8572 | -14.28% | 26590 / 22770 | 1404-06-24 (0.8571) | matches TSETMC table (dividend) |
| 1405-05-06 | 1405-05-18 | 0.3437 | -65.63% | 66480 / 23530 |  | not in TSETMC table (likely capital increase) |
| 1405-06-15 | 1405-06-22 | 0.9318 | -6.82% | 28010 / 27920 | 1405-06-17 (0.9316) | matches TSETMC table (dividend) |


- Days with |adjusted daily return| > 10% (Final or Close): 0

_none_



## Indices

- **شاخص کل**. File `data/raw/index_total.csv`, InsCode 32097828799138957. 1402-06-01 to 1405-06-31, 739 rows, 720 in the period. Duplicates 0. Missing vs calendar 0. Columns: Open, High, Low, Close, Volume. Daily |return| > 10%: 0.
- **شاخص کل (هم وزن)** (fetched as `شاخص هم وزن`). File `data/raw/index_equal_weight.csv`, InsCode 67130298613737946. 1402-06-01 to 1405-06-31, 739 rows, 720 in the period. Duplicates 0. Missing vs calendar 0. Columns: Open, High, Low, Close, Volume. Daily |return| > 10%: 0. **Decimal-shift errors (value 10x or 1/10 of the surrounding days): `Open` 1404-09-19 (x10), 1404-11-12 (x10); `Low` 1404-09-19 (x10), 1404-11-12 (x10).**
- **فلزات اساسی**. File `data/raw/sector_of_foolad.csv`, InsCode 32453344048876642. 1402-06-01 to 1405-06-31, 739 rows, 720 in the period. Duplicates 0. Missing vs calendar 0. Columns: High, Low, Close. Daily |return| > 10%: 0.
- **فرآورده‌های نفتی**. File `data/raw/sector_of_shepna.csv`, InsCode 12331083953323969. 1402-06-01 to 1405-06-31, 739 rows, 720 in the period. Duplicates 0. Missing vs calendar 0. Columns: High, Low, Close. Daily |return| > 10%: 10 (1404-03-19 -90.14%, 1404-03-20 +903.69%, 1404-03-28 -90.00%, 1404-03-31 +900.00%, 1404-04-01 -90.00%, 1404-04-02 +900.00%, 1404-04-03 -90.00%, 1404-04-04 +900.00%, 1404-04-07 -90.20%, 1404-04-08 +872.53%). **Decimal-shift errors (value 10x or 1/10 of the surrounding days): `High` 1404-03-19 (x0.1), 1404-03-28 (x0.1), 1404-04-01 (x0.1), 1404-04-03 (x0.1), 1404-04-07 (x0.1); `Low` 1404-03-19 (x0.1), 1404-03-28 (x0.1), 1404-04-01 (x0.1), 1404-04-03 (x0.1), 1404-04-07 (x0.1); `Close` 1404-03-19 (x0.1), 1404-03-28 (x0.1), 1404-04-01 (x0.1), 1404-04-03 (x0.1), 1404-04-07 (x0.1).**
- **خودرو و ساخت قطعات**. File `data/raw/sector_of_khodro.csv`, InsCode 20213770409093165. 1402-06-01 to 1405-06-31, 739 rows, 720 in the period. Duplicates 0. Missing vs calendar 0. Columns: High, Low, Close. Daily |return| > 10%: 2 (1404-02-02 +15.73%, 1404-05-08 -13.93%).
- **بانک‌ها و موسسات اعتباری** (fetched as `بانکها`). File `data/raw/sector_of_vbmellat.csv`, InsCode 72002976013856737. 1402-06-01 to 1405-06-31, 739 rows, 720 in the period. Duplicates 0. Missing vs calendar 0. Columns: High, Low, Close. Daily |return| > 10%: 0.
- **مخابرات**. File `data/raw/sector_of_akhaber.csv`, InsCode 41867092385281437. 1402-06-01 to 1405-06-31, 739 rows, 720 in the period. Duplicates 0. Missing vs calendar 0. Columns: High, Low, Close. Daily |return| > 10%: 1 (1404-02-07 +13.29%).
- **سرمایه‌گذاری‌ها** (fetched as `سرمایه گذاریها`). File `data/raw/sector_of_shasta.csv`, InsCode 34295935482222451. 1402-06-01 to 1405-06-31, 739 rows, 720 in the period. Duplicates 0. Missing vs calendar 0. Columns: High, Low, Close. Daily |return| > 10%: 0.
- **مواد و محصولات دارویی** (fetched as `مواد دارویی`). File `data/raw/sector_of_tipico.csv`, InsCode 3615666621538524. 1402-06-01 to 1405-06-31, 739 rows, 720 in the period. Duplicates 0. Missing vs calendar 0. Columns: High, Low, Close. Daily |return| > 10%: 0.


## CPI (Statistical Centre of Iran)

- File `data/external/cpi_iran_sci.csv`: 37 months, 1402-06 to 1405-06. Consecutive: yes. Missing months: none.
- Series: SCI, CPI of all households of the whole country (شاخص کل), base 1400=100. Source workbook: https://amar.org.ir/Portals/0/Statistics/ts_national_140506-14050719122615.xlsx. Upload date in the file name (Jalali): 1405-07-19.

Known-value check:

| month | expected | fetched | result |
|---|---|---|---|
| 1402-06 | 201.7 | 201.7326 | OK |
| 1403-06 | 264.7 | 264.7312 | OK |
| 1404-06 | 384.6 | 384.5593 | OK |
| 1405-05 | 700.1 | 700.1304 | OK |
| 1405-06 | 729.8 | 729.8394 | OK |

- SCI's monthly inflation vs the rate recomputed from the index: max absolute difference 0.0001 percentage points.

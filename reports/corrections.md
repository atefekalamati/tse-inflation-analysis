# Corrections log

Written by `src/process_data.py`. `data/raw` is never modified; corrections are applied in memory and only the processed panels contain corrected values (column `was_corrected` = true).

## Values corrected

| file | date (Jalali) | column | original | corrected | median of surrounding days | reason |
|---|---|---|---|---|---|---|
| data/raw/sector_of_shepna.csv | 1404-03-19 | High | 1,320,600 | 13,206,000 | 13,239,460 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-03-28 | High | 1,309,890 | 13,098,900 | 13,098,945 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-04-01 | High | 1,309,890 | 13,098,900 | 13,098,945 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-04-03 | High | 1,309,890 | 13,098,900 | 13,098,945 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-04-07 | High | 1,307,700 | 13,077,000 | 12,639,500 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-03-19 | Low | 1,301,800 | 13,018,000 | 13,182,477 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-03-28 | Low | 1,309,890 | 13,098,900 | 13,098,945 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-04-01 | Low | 1,309,890 | 13,098,900 | 13,098,945 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-04-03 | Low | 1,309,890 | 13,098,900 | 13,098,945 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-04-07 | Low | 1,283,930 | 12,839,300 | 12,374,761 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-03-19 | Close | 1,301,800 | 13,018,000 | 13,202,950 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-03-28 | Close | 1,309,890 | 13,098,900 | 13,098,945 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-04-01 | Close | 1,309,890 | 13,098,900 | 13,098,945 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-04-03 | Close | 1,309,890 | 13,098,900 | 13,098,945 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |
| data/raw/sector_of_shepna.csv | 1404-04-07 | Close | 1,283,930 | 12,839,300 | 12,374,761 | decimal shift in TSETMC source: value is 1/10 of the surrounding days |


## Known issues left uncorrected

These cells are wrong in the source but sit in columns the analysis does not use (only closing prices are used), so they are logged, not changed.

| file | date (Jalali) | column | row values | issue | action |
|---|---|---|---|---|---|
| data/raw/stock_shasta_adjusted.csv | 1402-07-17 | Open | Open=0, High=824, Low=798, Close=816 | Open = 0 in the TSETMC history (other prices normal) | none (column not used) |
| data/raw/stock_shasta_unadjusted.csv | 1402-07-17 | Open | Open=0, High=1,285, Low=1,244, Close=1,273 | Open = 0 in the TSETMC history (other prices normal) | none (column not used) |
| data/raw/index_equal_weight.csv | 1404-09-19 | Open | Open=9,876,410, High=1,000,740, Low=9,876,410, Close=1,000,740 | decimal shift: Open and Low are 10x the surrounding days (Close fine) | none (column not used) |
| data/raw/index_equal_weight.csv | 1404-11-12 | Open | Open=9,957,180, High=1,003,160, Low=9,957,180, Close=1,003,150 | decimal shift: Open and Low are 10x the surrounding days (Close fine) | none (column not used) |

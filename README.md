# Asia Express 2 Prima CZ – callsheety

Interaktivní přehled natáčecích callsheetů. Otevři `index.html` (jedna samostatná stránka, data jsou uvnitř) nebo zapni GitHub Pages: **Settings → Pages → Deploy from a branch → `main` / `/ (root)`**.

## Co v tom je

- Záložka pro každý den. **ND** je natáčecí den, přerušované záložky jsou mezi-dny (v názvech souborů `RR`, v callsheetu „REST & RECOVERY“), kde se netočí hlavní díl, ale jsou porady, lety a přesuny.
- Každý blok (co se v kolik točilo) se dá rozkliknout: tým, lokace, GPS s odkazem do mapy, délka, vzdálenost a jednotky (vany, security, CP…) s účastníky, které na lokaci přijíždějí, včetně časů a poznámek.
- Pod seznamem bloků jsou panely: všechny jednotky s časy odjezdů, lety, prep, hotely, jídlo a poznámky produkce.
- Kamery callsheety neuvádějí, proto v přehledu nejsou.

## Číslování dní

| Callsheet | Přehled |
|---|---|
| Day 5, 6, 7 | ND4, ND5, ND6 |
| Day 8 (RR) | mezi-den 2. 11. |
| Day 9, 10, 11 | ND7, ND8, ND9 |
| Day 12 (RR) | mezi-den 6. 11. |
| Day 13, 14, 15 | ND10, ND11, ND12 |
| Day 16 | chybí (callsheet nebyl v podkladech), počítá se jako ND13 |
| Day 17 (RR) | mezi-den 11. 11. |
| Day 18, 19, 20 | ND14, ND15, ND16 |
| Day 21 (RR) | mezi-den 15. 11. |
| Day 22, 23, 24 | ND17, ND18, ND19 |

Datum se počítá z čísla dne (Day 5 = pátek 30. 10. 2026). V callsheetech jsou překlepy v hlavičce: Day 21 má „Day 20 of 24“, Day 22 má „12th November“, Day 23 má „16th November“. Stránka u těchto dnů ukazuje upozornění.

## Jak přegenerovat

Potřebuje Python 3 s `pdfplumber` a nainstalované `pdftotext` (poppler).

```bash
python3 scripts/parse_callsheets.py <složka s PDF callsheety> data/days.json
python3 scripts/build_site.py data/days.json src/template.html index.html
```

PDF callsheety v repozitáři nejsou. U letů se z callsheetů přebírá čas, číslo letu, trasa, letiště a poznámky, jména cestujících se do dat neukládají.

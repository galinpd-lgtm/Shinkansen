# Договорът: forecast.json

Агентът (GX10) го пише, всеки сайт го чете. Сменя се само с нова версия (`schema_version`).

| Поле | Какво е |
|---|---|
| `schema_version` | "1" |
| `generated_at` | ISO време на изчисляването |
| `city`, `lat`, `lon` | от конфигурацията |
| `sources_ok` / `sources_failed` | кои източници са отговорили — ако падне един, сайтът продължава |
| `hours[]` | час по час: `t`, `temp_c`, `precip_pct`, `gust_kmh`, `cloud_pct`, `thunder`, `spread` (разминаване между източниците) |
| `days[]` | ден: `date`, `risk` (low/medium/high), `agreement` (колко източника са съгласни) |
| `events[]` | проява: `title`, `start`, `risk`, `scene` (clear/clouds/rain/storm/heat/snow) |
| `summary` | едно-три изречения от локалния модел |

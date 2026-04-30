-- ============================================================
-- TAB Racing Overlay Hunter - Supabase Schema
-- Run this in Supabase SQL editor
-- ============================================================

create table if not exists meetings (
    id                  text primary key,
    meeting_date        date not null,
    venue_name          text not null,
    venue_state         text,
    racing_type         text not null,
    created_at          timestamptz default now()
);

create table if not exists races (
    id                  text primary key,
    meeting_id          text references meetings(id),
    race_number         int not null,
    race_name           text,
    jump_time           timestamptz not null,
    distance_metres     int,
    field_size          int,
    status              text default 'upcoming',
    created_at          timestamptz default now()
);

create index if not exists idx_races_jump_time on races(jump_time);
create index if not exists idx_races_status on races(status);

create table if not exists snapshots (
    id                      bigserial primary key,
    race_id                 text references races(id),
    captured_at             timestamptz not null,
    seconds_to_jump         int,
    racing_type             text,        -- Thoroughbred, Harness, Greyhound

    -- Win odds for all runners {runner_number: odds}
    win_odds                jsonb not null,

    -- Pool totals at snapshot time
    quinella_pool_total     numeric(12,2),
    exacta_pool_total       numeric(12,2),
    trifecta_pool_total     numeric(12,2),

    -- Raw approximates {combo: dividend}
    quinella_approx         jsonb,
    exacta_approx           jsonb,
    trifecta_approx         jsonb,

    -- Fair values {combo: fair_dividend}
    quinella_fair           jsonb,
    exacta_fair             jsonb,
    trifecta_fair           jsonb,

    -- Edge ratio {combo: edge_pct}  (true_prob% - pool_share%)
    -- positive = underbet relative to true probability
    quinella_edge           jsonb,
    exacta_edge             jsonb,
    trifecta_edge           jsonb,

    -- Top 3 combinations by edge ratio
    -- stored as [{rank, combo, odds_a, odds_b, true_prob_pct, pool_share_pct,
    --             edge_pct, implied_stake, dividend}]
    quinella_top3           jsonb,
    exacta_top3             jsonb,
    trifecta_top3           jsonb,

    created_at              timestamptz default now()
);

create index if not exists idx_snapshots_race_id on snapshots(race_id);

create table if not exists results (
    id                  bigserial primary key,
    race_id             text references races(id) unique,
    captured_at         timestamptz not null,
    result_raw          jsonb,

    first_place         int,
    second_place        int,
    third_place         int,
    fourth_place        int,

    quinella_combo      text,
    quinella_dividend   numeric(10,2),
    exacta_combo        text,
    exacta_dividend     numeric(10,2),
    trifecta_combo      text,
    trifecta_dividend   numeric(10,2),
    first_four_combo    text,
    first_four_dividend numeric(10,2),

    created_at          timestamptz default now()
);

-- ============================================================
-- Analysis view - joins top3 snapshot with actual results
-- ============================================================
create or replace view overlay_analysis as
with top3_expanded as (
    -- Unnest the quinella top3 array into individual rows
    select
        s.race_id,
        s.captured_at,
        s.seconds_to_jump,
        s.racing_type,
        s.quinella_pool_total,
        (item->>'rank')::int          as rank,
        item->>'combo'                as combo,
        (item->>'true_prob_pct')::numeric as true_prob_pct,
        (item->>'pool_share_pct')::numeric as pool_share_pct,
        (item->>'edge_pct')::numeric  as edge_pct,
        (item->>'implied_stake')::numeric as implied_stake,
        (item->>'dividend')::numeric  as snapshot_dividend,
        (item->>'odds_a')::numeric    as odds_a,
        (item->>'odds_b')::numeric    as odds_b
    from snapshots s,
    jsonb_array_elements(s.quinella_top3) as item
    where s.quinella_top3 is not null
)
select
    t.race_id,
    m.venue_name,
    m.venue_state,
    t.racing_type,
    r.race_name,
    r.field_size,
    r.jump_time,
    t.rank,
    t.combo,
    t.odds_a,
    t.odds_b,
    t.true_prob_pct,
    t.pool_share_pct,
    t.edge_pct,
    t.implied_stake,
    t.snapshot_dividend,
    t.quinella_pool_total,
    res.quinella_combo      as winner_combo,
    res.quinella_dividend   as actual_dividend,
    case
        when t.combo = res.quinella_combo
        then res.quinella_dividend
        else 0
    end                     as return,
    case
        when t.combo = res.quinella_combo
        then res.quinella_dividend - t.snapshot_dividend
        else 0 - t.snapshot_dividend
    end                     as pnl
from top3_expanded t
join races r        on t.race_id = r.id
join meetings m     on r.meeting_id = m.id
left join results res on t.race_id = res.race_id
order by r.jump_time desc, t.rank;

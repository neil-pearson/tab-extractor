-- Migration: add edge ratio and top3 columns to existing snapshots table
-- Run this in Supabase SQL editor if you already have the old schema

alter table snapshots
    add column if not exists racing_type          text,
    add column if not exists quinella_pool_total  numeric(12,2),
    add column if not exists exacta_pool_total    numeric(12,2),
    add column if not exists trifecta_pool_total  numeric(12,2),
    add column if not exists quinella_edge        jsonb,
    add column if not exists exacta_edge          jsonb,
    add column if not exists trifecta_edge        jsonb,
    add column if not exists quinella_top3        jsonb,
    add column if not exists exacta_top3          jsonb,
    add column if not exists trifecta_top3        jsonb;

-- Drop old overlay columns (optional - can keep for reference)
-- alter table snapshots
--     drop column if exists best_quinella_combo,
--     drop column if exists best_quinella_overlay,
--     drop column if exists best_exacta_combo,
--     drop column if exists best_exacta_overlay,
--     drop column if exists best_trifecta_combo,
--     drop column if exists best_trifecta_overlay;

-- Create the analysis view (or replace if exists)
create or replace view overlay_analysis as
with top3_expanded as (
    select
        s.race_id,
        s.captured_at,
        s.seconds_to_jump,
        s.racing_type,
        s.quinella_pool_total,
        (item->>'rank')::int              as rank,
        item->>'combo'                    as combo,
        (item->>'true_prob_pct')::numeric as true_prob_pct,
        (item->>'pool_share_pct')::numeric as pool_share_pct,
        (item->>'edge_pct')::numeric      as edge_pct,
        (item->>'implied_stake')::numeric as implied_stake,
        (item->>'dividend')::numeric      as snapshot_dividend,
        (item->>'odds_a')::numeric        as odds_a,
        (item->>'odds_b')::numeric        as odds_b
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

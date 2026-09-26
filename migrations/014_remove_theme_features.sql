-- Retire theme discovery/screening tables while preserving research audit history.
DROP TABLE IF EXISTS finance.theme_reviews CASCADE;
DROP TABLE IF EXISTS finance.theme_evidence CASCADE;
DROP TABLE IF EXISTS finance.theme_memberships CASCADE;
DROP TABLE IF EXISTS finance.themes CASCADE;
DROP TABLE IF EXISTS finance.research_feature_snapshots CASCADE;

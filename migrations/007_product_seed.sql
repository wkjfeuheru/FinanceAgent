-- 由 tools/generate_product_seed.py 生成，请勿手工编辑。
-- 幂等：重复执行会更新同代码产品/持仓/业绩，不产生重复行。

INSERT INTO finance.products (code, name, type, establish_date, scale, manager, company, management_fee, custody_fee, subscription_fee, redemption_fee, risk_level, recommended_holding_period, investment_target, investment_strategy) VALUES
    ('110011', '易方达中小盘混合', 'fund', '2008-06-19', 210.5, '张坤', '易方达基金', 1.5, 0.25, 1.5, '0.5%', 'R3 中风险', 'long', '通过投资于具有良好流动性的金融工具，追求长期资本增值。', '自下而上精选个股，集中持有具备长期竞争力的公司。'),
    ('000001', '华夏成长混合', 'fund', '2001-12-18', 48.2, '示例经理', '华夏基金', 1.5, 0.25, 1.5, '0.5%', 'R3 中风险', 'medium', '投资于成长型上市公司，分享中国经济成长成果。', '以成长性为核心，兼顾估值与行业景气度。'),
    ('510300', '华泰柏瑞沪深300ETF', 'etf', '2012-05-04', 1200.0, '示例经理', '华泰柏瑞基金', 0.5, 0.1, 0.0, '0', 'R4 中高风险', 'long', '紧密跟踪沪深300指数，追求跟踪偏离度和跟踪误差最小化。', '完全复制法被动跟踪标的指数。'),
    ('003003', '华夏现金增利货币A', 'fund', '2004-04-07', 300.0, '示例经理', '华夏基金', 0.33, 0.1, 0.0, '0', 'R1 低风险', 'short', '在保持本金安全与资产流动性的前提下，追求稳定收益。', '投资于短期货币市场工具。'),
    ('040025', '华安双债添利债券A', 'fund', '2013-03-15', 12.6, '示例经理', '华安基金', 0.7, 0.2, 0.8, '0.1%', 'R2 中低风险', 'medium', '通过债券投资获取稳定收益，控制回撤。', '以中高等级信用债与利率债为主，适度杠杆。'),
    ('161725', '招商中证白酒指数A', 'fund', '2015-05-27', 480.0, '示例经理', '招商基金', 1.0, 0.2, 1.0, '0.5%', 'R4 中高风险', 'long', '紧密跟踪中证白酒指数，分享白酒行业成长。', '指数化被动投资，行业集中度较高。'),
    ('999999', '数据缺失示例基金''O', 'fund', '2010-01-01', 1.0, '示例经理', '示例基金', NULL, NULL, NULL, '', '未披露', '', '', '')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, type = EXCLUDED.type, establish_date = EXCLUDED.establish_date, scale = EXCLUDED.scale, manager = EXCLUDED.manager, company = EXCLUDED.company, management_fee = EXCLUDED.management_fee, custody_fee = EXCLUDED.custody_fee, subscription_fee = EXCLUDED.subscription_fee, redemption_fee = EXCLUDED.redemption_fee, risk_level = EXCLUDED.risk_level, recommended_holding_period = EXCLUDED.recommended_holding_period, investment_target = EXCLUDED.investment_target, investment_strategy = EXCLUDED.investment_strategy;

DELETE FROM finance.product_holdings WHERE product_code IN ('110011', '000001', '510300', '003003', '040025', '161725', '999999');

INSERT INTO finance.product_holdings (product_code, stock_name, stock_code, weight, rank, report_date) VALUES
    ('110011', '示例股票A', '600519', 9.8, 1.0, '2026-06-30'),
    ('110011', '示例股票B', '000858', 8.1, 2.0, '2026-06-30'),
    ('000001', '示例股票C', '600036', 4.2, 1.0, '2026-03-31'),
    ('161725', '示例股票A', '600519', 15.0, 1.0, '2026-06-30');

DELETE FROM finance.product_performance WHERE product_code IN ('110011', '000001', '510300', '003003', '040025', '161725', '999999');

INSERT INTO finance.product_performance (product_code, nav, return_1m, return_3m, return_6m, return_1y, return_3y, max_drawdown, volatility, sharpe_ratio, update_date) VALUES
    ('110011', 3.85, 0.021, 0.045, 0.083, 0.126, 0.311, 0.187, 0.162, 0.78, '2026-09-08'),
    ('000001', 1.42, 0.005, 0.012, 0.019, 0.041, 0.088, 0.223, 0.171, 0.24, '2026-02-10'),
    ('510300', 4.12, 0.018, 0.039, 0.071, 0.112, 0.205, 0.254, 0.148, 0.66, '2026-09-08'),
    ('003003', 1.0, 0.0016, 0.0048, 0.0096, 0.0195, 0.0612, 0.0, 0.002, 2.1, '2026-09-08'),
    ('040025', 1.31, 0.004, 0.011, 0.022, 0.045, 0.142, 0.052, 0.038, 1.02, '2026-09-05'),
    ('161725', 1.05, -0.012, -0.028, -0.011, 0.033, -0.086, 0.412, 0.238, 0.09, '2026-09-08');

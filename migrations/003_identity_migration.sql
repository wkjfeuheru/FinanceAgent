DELETE FROM finance.conversation_messages
WHERE conversation_id IN (
    SELECT c.conversation_id FROM finance.conversations c
    LEFT JOIN finance.users u ON u.customer_id = c.customer_id
    WHERE u.customer_id IS NULL
);
DELETE FROM finance.conversations c
WHERE NOT EXISTS (SELECT 1 FROM finance.users u WHERE u.customer_id = c.customer_id);
DELETE FROM finance.user_profiles p
WHERE NOT EXISTS (SELECT 1 FROM finance.users u WHERE u.customer_id = p.customer_id);
DELETE FROM finance.agent_runs r
WHERE NOT EXISTS (SELECT 1 FROM finance.users u WHERE u.customer_id = r.customer_id);
ALTER TABLE finance.conversations DROP CONSTRAINT IF EXISTS conversations_customer_id_fkey;
ALTER TABLE finance.conversations ADD CONSTRAINT conversations_customer_id_fkey
    FOREIGN KEY (customer_id) REFERENCES finance.users(customer_id) ON DELETE CASCADE;
ALTER TABLE finance.user_profiles DROP CONSTRAINT IF EXISTS user_profiles_customer_id_fkey;
ALTER TABLE finance.user_profiles ADD CONSTRAINT user_profiles_customer_id_fkey
    FOREIGN KEY (customer_id) REFERENCES finance.users(customer_id) ON DELETE CASCADE;
ALTER TABLE finance.agent_runs DROP CONSTRAINT IF EXISTS agent_runs_customer_id_fkey;
ALTER TABLE finance.agent_runs ADD CONSTRAINT agent_runs_customer_id_fkey
    FOREIGN KEY (customer_id) REFERENCES finance.users(customer_id) ON DELETE CASCADE;
DROP TABLE IF EXISTS finance.customers;

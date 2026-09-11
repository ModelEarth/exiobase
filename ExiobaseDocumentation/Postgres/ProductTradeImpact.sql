CREATE TABLE producttradeimpact (
    trade_impact_id SERIAL PRIMARY KEY,
    product_category VARCHAR(255),       -- e.g., 'Plastics, basic'
    impact_category VARCHAR(255),        -- e.g., 'Carbon', 'EUR', 'Land'
    level NUMERIC(15,2),          -- e.g., -100000.0
    unit VARCHAR(255),                   -- e.g., 'kg', 'EUR', 'km²'
    year INT,                            -- e.g., 2021
    factor VARCHAR(255),                 -- air emissions, energy etc.
    from_country VARCHAR(255),           -- Optional, if available
    to_country VARCHAR(255)              -- Optional, if available
);
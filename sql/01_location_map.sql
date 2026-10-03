-- =====================================================================
-- 01_location_map.sql : manual mapping table for location variants (C13)
-- Built from a fuzzy review of the 200 most frequent normalised locations.
-- Only clear spelling / suffix variants are mapped. Distinct places that
-- merely look alike (JAIPUR vs RAIPUR, NELLORE vs VELLORE, MANGALORE vs
-- BANGALORE) are deliberately NOT merged. DELHI and NEW DELHI are kept
-- separate because the source records them as different locations [A].
-- =====================================================================

INSERT INTO location_map (variant, clean_city) VALUES
    -- Mumbai region
    ('MUMABAI', 'MUMBAI'), ('DMUMBAI', 'MUMBAI'), ('W MUMBAI', 'MUMBAI'), ('E MUMBAI', 'MUMBAI'),
    ('BOMBAY', 'MUMBAI'),
    ('NAVIMUMBAI', 'NAVI MUMBAI'),
    ('THANE W', 'THANE'), ('W THANE', 'THANE'), ('THANE WEST', 'THANE'),
    ('THANE E', 'THANE'), ('E THANE', 'THANE'), ('THANE EAST', 'THANE'),
    -- Delhi NCR
    ('NEWDELHI', 'NEW DELHI'), ('NEW DELH', 'NEW DELHI'), ('NEW DLEHI', 'NEW DELHI'),
    ('N DELHI', 'NEW DELHI'), ('PNEW DELHI', 'NEW DELHI'),
    ('GURGOAN', 'GURGAON'), ('GURAGAON', 'GURGAON'), ('GIURGAON', 'GURGAON'),
    ('GURAON', 'GURGAON'), ('GURUGRAM', 'GURGAON'),
    ('GAZIABAD', 'GHAZIABAD'), ('GHAZAIBAD', 'GHAZIABAD'),
    ('FRIDABAD', 'FARIDABAD'),
    ('GREATAR NOIDA', 'GREATER NOIDA'), ('GREATER NOIDA WEST', 'GREATER NOIDA'),
    ('SONEPAT', 'SONIPAT'),
    -- Bengaluru (dominant spelling in the data is BANGALORE)
    ('BANGLORE', 'BANGALORE'), ('BANAGALORE', 'BANGALORE'), ('BENGALORE', 'BANGALORE'),
    ('3 BANGALORE', 'BANGALORE'), ('BENGALURU', 'BANGALORE'), ('BANGALURU', 'BANGALORE'),
    ('BENGLURU', 'BANGALORE'), ('BENGALOORU', 'BANGALORE'),
    -- Hyderabad region
    ('HYDERABAD AP', 'HYDERABAD'), ('SECUDERABAD', 'SECUNDERABAD'),
    ('RANGAREDDY', 'RANGA REDDY'), ('RANGA REDDI', 'RANGA REDDY'), ('RANGAREDDI', 'RANGA REDDY'),
    ('K V RANGA REDDY', 'RANGA REDDY'), ('RANGAREDDY DT', 'RANGA REDDY'),
    ('KARIM NAGAR', 'KARIMNAGAR'), ('KORIMNAGAR', 'KARIMNAGAR'),
    -- West
    ('AHMADABAD', 'AHMEDABAD'), ('AHEMDABAD', 'AHMEDABAD'),
    ('BARODA', 'VADODARA'),
    ('GHANDHINAGAR', 'GANDHINAGAR'), ('GANDHI NAGAR', 'GANDHINAGAR'),
    ('NASIK', 'NASHIK'),
    ('POONA', 'PUNE'),
    -- East
    ('CALCUTTA', 'KOLKATA'),
    ('HAWRAH', 'HOWRAH'), ('HOOGLY', 'HOOGHLY'),
    ('NORTH 24 PARAGANAS', 'NORTH 24 PARGANAS'), ('NORT 24 PARGANAS', 'NORTH 24 PARGANAS'),
    ('NORTH 24 PGS', 'NORTH 24 PARGANAS'), ('SOUTH 24 PGS', 'SOUTH 24 PARGANAS'),
    ('BHUBANESWAR', 'BHUBANESHWAR'), ('BUBANESWAR', 'BHUBANESHWAR'),
    ('RACHI', 'RANCHI'),
    -- South
    ('MADRAS', 'CHENNAI'),
    ('VISHAKHAPATNAM', 'VISAKHAPATNAM'), ('VISAKHAPATANAM', 'VISAKHAPATNAM'),
    ('VISHAKAPATANAM', 'VISAKHAPATNAM'), ('VIZAG', 'VISAKHAPATNAM'),
    ('COMBATORE', 'COIMBATORE'),
    ('ERANAKULAM', 'ERNAKULAM'), ('ERNAKULAM KL', 'ERNAKULAM'),
    ('COCHIN', 'KOCHI'), ('KOCHIIN', 'KOCHI'),
    ('TRIVANDRUM', 'THIRUVANANTHAPURAM'),
    ('CALICUT', 'KOZHIKODE'),
    ('TRISSUR', 'THRISSUR'),
    ('PUDUCHERRY', 'PONDICHERRY'),
    ('MANGALURU', 'MANGALORE'), ('BELAGAVI', 'BELGAUM'), ('MYSURU', 'MYSORE'),
    ('VELLORE DT', 'VELLORE'), ('NELLORE 1', 'NELLORE'),
    ('KANCHIPURAM', 'KANCHEEPURAM'), ('KANCHEEPURAM DT', 'KANCHEEPURAM'),
    ('KANCHEEPURAM DIST', 'KANCHEEPURAM'),
    ('SRIPERUMBUDUR TK', 'SRIPERUMBUDUR'),
    ('MUDURAI', 'MADURAI'), ('MADURAI DT', 'MADURAI'),
    -- North / Central
    ('S A S NAGAR', 'SAS NAGAR'),
    ('ZIRKPUR', 'ZIRAKPUR'),
    ('BHATINDA', 'BATHINDA'),
    ('YAMUNA NAGAR', 'YAMUNANAGAR'),
    ('VARNASI', 'VARANASI'), ('VARANSI', 'VARANASI'),
    ('AGARA', 'AGRA');

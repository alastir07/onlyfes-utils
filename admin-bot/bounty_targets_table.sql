-- Run this in Supabase SQL Editor
-- Introduces bounty_targets as the source of truth for weekly bounty items,
-- replacing the old Discord "Full item list" thread message.

CREATE TABLE public.bounty_targets (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bounty_name character varying NOT NULL,
    wiki_link text,
    image_url text,
    created_at timestamp with time zone NOT NULL DEFAULT now()
);

-- Link bounties rolled after this migration back to the target they were rolled from.
-- Nullable: historical bounties predate bounty_targets and are backfilled on a best-effort
-- basis below; item_name is kept on bounties as a denormalized snapshot either way.
ALTER TABLE public.bounties ADD COLUMN bounty_target_id bigint REFERENCES public.bounty_targets(id);

INSERT INTO public.bounty_targets (bounty_name, wiki_link, image_url) VALUES
('Obsidian Cape', 'https://oldschool.runescape.wiki/w/Obsidian_cape', 'https://oldschool.runescape.wiki/w/Obsidian_cape#/media/File:Obsidian_cape_detail.png'),
('Dragon Spear', 'https://oldschool.runescape.wiki/w/Dragon_spear', 'https://oldschool.runescape.wiki/w/Dragon_spear#/media/File:Dragon_spear_detail.png'),
('Elder Chaos robe piece', 'https://oldschool.runescape.wiki/w/Elder_chaos_druid_robes', 'https://oldschool.runescape.wiki/w/Elder_chaos_druid_robes#/media/File:Elder_chaos_druid_robes_equipped_male.png'),
('Scurrius'' Spine', 'https://oldschool.runescape.wiki/w/Scurrius%27_spine', 'https://oldschool.runescape.wiki/w/Scurrius%27_spine#/media/File:Scurrius''_spine_detail.png'),
('Immaculate mole Skin', 'https://oldschool.runescape.wiki/w/Immaculate_mole_skin', 'https://oldschool.runescape.wiki/w/Immaculate_mole_skin#/media/File:Immaculate_mole_skin_detail.png'),
('Steel ring', 'https://oldschool.runescape.wiki/w/Steel_ring', 'https://oldschool.runescape.wiki/w/Steel_ring#/media/File:Steel_ring_detail.png'),
('Berserker ring / Warrior ring / Archers Ring / Seers Ring', 'https://oldschool.runescape.wiki/w/Dagannoth_Kings', NULL),
('Dragon Axe', 'https://oldschool.runescape.wiki/w/Dragon_axe', 'https://oldschool.runescape.wiki/w/Dragon_axe#/media/File:Dragon_axe_detail.png'),
('Burning Claw / Tormented Synapse', 'https://oldschool.runescape.wiki/w/Tormented_Demon', NULL),
('Pristine Spider Silk / Sarachnis cudgel', 'https://oldschool.runescape.wiki/w/Sarachnis', NULL),
('Blue Moon Armour', 'https://oldschool.runescape.wiki/w/Blue_moon_armour', 'https://oldschool.runescape.wiki/w/Blue_moon_armour#/media/File:Blue_moon_armour_equipped_male.png'),
('Blood Moon Armour', 'https://oldschool.runescape.wiki/w/Blood_moon_armour', 'https://oldschool.runescape.wiki/w/Blood_moon_armour#/media/File:Blood_moon_armour_equipped_male.png'),
('Eclipse Moon Armour', 'https://oldschool.runescape.wiki/w/Eclipse_moon_armour', 'https://oldschool.runescape.wiki/w/Eclipse_moon_armour#/media/File:Eclipse_moon_armour_equipped_male.png'),
('Dragon 2h sword', 'https://oldschool.runescape.wiki/w/Dragon_2h_sword', 'https://oldschool.runescape.wiki/w/Dragon_2h_sword#/media/File:Dragon_2h_sword_detail.png'),
('Dragon Pickaxe', 'https://oldschool.runescape.wiki/w/Dragon_pickaxe', 'https://oldschool.runescape.wiki/w/Dragon_pickaxe#/media/File:Dragon_pickaxe_detail.png'),
('Armadyl Armour', 'https://oldschool.runescape.wiki/w/Armadyl_armour', 'https://oldschool.runescape.wiki/w/Armadyl_armour#/media/File:Armadyl_armour_equipped_male.png'),
('Bandos Armour', 'https://oldschool.runescape.wiki/w/Bandos_armour', 'https://oldschool.runescape.wiki/images/Bandos_armour_equipped_male.png?23de4'),
('GWD Hilt', 'https://oldschool.runescape.wiki/w/Godsword_hilt', NULL),
('K''ril Tsutsaroth Unique (not including Hilt / godsword shards)', 'https://oldschool.runescape.wiki/w/K%27ril_Tsutsaroth', 'https://oldschool.runescape.wiki/w/K%27ril_Tsutsaroth#/media/File:K''ril_Tsutsaroth.png'),
('Commander Zilyana Unique (not including Hilt / godsword shards)', 'https://oldschool.runescape.wiki/w/Commander_Zilyana', 'https://oldschool.runescape.wiki/w/Commander_Zilyana#/media/File:Commander_Zilyana.png'),
('Hueycoatl Unique', 'https://oldschool.runescape.wiki/w/The_Hueycoatl', 'https://oldschool.runescape.wiki/w/Dragon_hunter_wand#/media/File:Dragon_hunter_wand_detail.png'),
('Odium Shard 1 / Maledicition Shard 1', 'https://oldschool.runescape.wiki/w/Chaos_Fanatic', 'https://oldschool.runescape.wiki/w/Chaos_Fanatic#/media/File:Chaos_Fanatic.png'),
('Odium Shard 2 / Maledicition Shard 2', 'https://oldschool.runescape.wiki/w/Crazy_archaeologist', 'https://oldschool.runescape.wiki/w/Crazy_archaeologist#/media/File:Crazy_archaeologist.png'),
('Odium Shard 3 / Maledicition Shard 3', 'https://oldschool.runescape.wiki/w/Scorpia', 'https://oldschool.runescape.wiki/w/Scorpia#/media/File:Scorpia.png'),
('Fedora', 'https://oldschool.runescape.wiki/w/Fedora', 'https://oldschool.runescape.wiki/w/Fedora#/media/File:Fedora_detail.png'),
('Any Pet (not including Generic pets)', 'https://oldschool.runescape.wiki/w/Pet', 'https://oldschool.runescape.wiki/w/Bloodhound#/media/File:Bloodhound_(follower).png'),
('Glacial Temotli', 'https://oldschool.runescape.wiki/w/Glacial_temotli', 'https://oldschool.runescape.wiki/w/Glacial_temotli#/media/File:Glacial_temotli_detail.png'),
('Fire element staff crown / Mystic vigour prayer scroll', 'https://oldschool.runescape.wiki/w/Branda_the_Fire_Queen', 'https://oldschool.runescape.wiki/images/Fire_element_staff_crown_detail.png?db8f6'),
('Ice element staff crown / Deadeye prayer scroll', 'https://oldschool.runescape.wiki/w/Eldric_the_Ice_King', 'https://oldschool.runescape.wiki/images/Ice_element_staff_crown_detail.png?db8f6'),
('Doom Unique', 'https://oldschool.runescape.wiki/w/Doom_of_Mokhaiotl', 'https://oldschool.runescape.wiki/w/Doom_of_Mokhaiotl#/media/File:Doom_of_Mokhaiotl.png'),
('Zulrah Unique', 'https://oldschool.runescape.wiki/w/Zulrah', 'https://oldschool.runescape.wiki/w/Zulrah#/media/File:Zulrah_(serpentine).png'),
('Venator Shard', 'https://oldschool.runescape.wiki/w/Venator_shard', 'https://oldschool.runescape.wiki/images/Venator_shard_detail.png?3ad3e'),
('Ancient Icon', 'https://oldschool.runescape.wiki/w/Ancient_icon', 'https://oldschool.runescape.wiki/images/Ancient_icon_detail.png?137e5'),
('Chromium Ingot', 'https://oldschool.runescape.wiki/w/Chromium_ingot', 'https://oldschool.runescape.wiki/images/Chromium_ingot_detail.png?b410d'),
('Any DT2 Vestige / gold ring drop', NULL, NULL),
('Any Soul reaper axe piece / Any Virtus robe piece', NULL, NULL),
('Dragon metal sheet', 'https://oldschool.runescape.wiki/w/Dragon_metal_sheet', 'https://oldschool.runescape.wiki/images/Dragon_metal_sheet_detail.png?e2090'),
('Brimstone key', 'https://oldschool.runescape.wiki/w/Brimstone_key', 'https://oldschool.runescape.wiki/images/Brimstone_key_detail.png?60e5e'),
('Long bone', 'https://oldschool.runescape.wiki/w/Long_bone', 'https://oldschool.runescape.wiki/images/Long_bone_detail.png?1e8a4'),
('Curved bone', 'https://oldschool.runescape.wiki/w/Curved_bone', 'https://oldschool.runescape.wiki/images/Curved_bone_detail.png?2315b'),
('Gnome Restaurant Clog Item', 'https://oldschool.runescape.wiki/w/Gnome_Restaurant', 'https://oldschool.runescape.wiki/w/Gnome_child#/media/File:Gnome_child.png'),
('Gauntlet Weapon Seed / Armour Seed', 'https://oldschool.runescape.wiki/w/Reward_Chest_(The_Gauntlet)', 'https://oldschool.runescape.wiki/w/Corrupted_Hunllef#/media/File:Corrupted_Hunllef.png'),
('Fire Cape', 'https://oldschool.runescape.wiki/w/Fire_cape', 'https://oldschool.runescape.wiki/images/Fire_cape_detail.png?f1d08'),
('Tome of water (empty)', 'https://oldschool.runescape.wiki/w/Tome_of_water#Empty', 'https://oldschool.runescape.wiki/images/Tome_of_water_%28empty%29_detail.png?2502c'),
('Tome of fire (empty)', 'https://oldschool.runescape.wiki/w/Tome_of_fire#Empty', 'https://oldschool.runescape.wiki/images/Tome_of_fire_%28empty%29_detail.png?b9bae'),
('Crystal Tool Seed', 'https://oldschool.runescape.wiki/w/Crystal_tool_seed', 'https://oldschool.runescape.wiki/images/Crystal_tool_seed_detail.png?d8a0b'),
('Cox Purple', 'https://oldschool.runescape.wiki/w/Ancient_chest#Loot_table', 'https://oldschool.runescape.wiki/w/Twisted_bow#/media/File:Twisted_bow_detail.png'),
('Toa Purple', 'https://oldschool.runescape.wiki/w/Chest_(Tombs_of_Amascut)#Opened', 'https://oldschool.runescape.wiki/w/Tumeken%27s_shadow#/media/File:Tumeken''s_shadow_detail.png'),
('Tob Purple', 'https://oldschool.runescape.wiki/w/Monumental_chest#Closed_(player''s_unique)', 'https://oldschool.runescape.wiki/w/Scythe_of_Vitur#/media/File:Scythe_of_Vitur_detail.png'),
('Zenyte Shard / Ballista Piece', 'https://oldschool.runescape.wiki/w/Demonic_gorilla', 'https://oldschool.runescape.wiki/w/Zenyte_shard#/media/File:Zenyte_shard_detail.png'),
('Grotesque Guardians Unique', 'https://oldschool.runescape.wiki/w/Grotesque_Guardians', 'https://oldschool.runescape.wiki/w/Grotesque_Guardians#/media/File:Dawn.png'),
('Cerberus Unique', 'https://oldschool.runescape.wiki/w/Cerberus', 'https://oldschool.runescape.wiki/w/Cerberus#/media/File:Cerberus.png'),
('Any ancient Statuette from revs', 'https://oldschool.runescape.wiki/w/Ancient_totem', 'https://oldschool.runescape.wiki/images/Ancient_totem_detail.png?63bac'),
('Revenant Weapon / Amulet of Avarice / Skull of vet''ion / Claws of callisto / Fangs of venenatis', NULL, NULL),
('Crawling hand (Item)', 'https://oldschool.runescape.wiki/w/Crawling_hand_(item)', 'https://oldschool.runescape.wiki/images/Crawling_hand_%28item%29_detail.png?d6a6b'),
('Leaf-Bladed Sword / Battleaxe', 'https://oldschool.runescape.wiki/w/Kurask', 'https://oldschool.runescape.wiki/w/Leaf-bladed_battleaxe#/media/File:Leaf-bladed_battleaxe_detail.png'),
('Shark Paint', 'https://oldschool.runescape.wiki/w/Shark_paint', 'https://oldschool.runescape.wiki/images/Shark_paint_detail.png?6ebb1'),
('Unsired', 'https://oldschool.runescape.wiki/w/Unsired', 'https://oldschool.runescape.wiki/images/Unsired_detail.png?36d00'),
('Trident of the seas / Kraken Tentacle', 'https://oldschool.runescape.wiki/w/Kraken#Kraken', NULL),
('Bottled Storm', 'https://oldschool.runescape.wiki/w/Bottled_storm', 'https://oldschool.runescape.wiki/images/Bottled_storm_detail.png?6fd35'),
('Void Knight Mace', 'https://oldschool.runescape.wiki/w/Void_knight_mace', 'https://oldschool.runescape.wiki/images/Void_knight_mace_detail.png?3a2b6'),
('Amulet of the damned', 'https://oldschool.runescape.wiki/w/Amulet_of_the_damned', 'https://oldschool.runescape.wiki/images/Amulet_of_the_damned_%28full%29_detail.png?9f349'),
('Yama Unique (Oathplate / Soulflame horn)', 'https://oldschool.runescape.wiki/w/Yama', NULL),
('Any Voidwaker Piece', 'https://oldschool.runescape.wiki/w/Voidwaker', 'https://oldschool.runescape.wiki/images/Voidwaker_detail.png?01835'),
('Belle''s Folly (tarnished)', 'https://oldschool.runescape.wiki/w/Belle%27s_folly_(tarnished)', 'https://oldschool.runescape.wiki/images/Belle%27s_folly_%28tarnished%29_detail.png?77da3'),
('Ahrims Piece', 'https://oldschool.runescape.wiki/images/Ahrim%27s_robes_equipped_male.png?a9d20', 'https://oldschool.runescape.wiki/images/Ahrim%27s_robes_equipped_male.png?a9d20'),
('Dharoks Piece', 'https://oldschool.runescape.wiki/images/Dharok%27s_armour_equipped_male.png?3d05c', 'https://oldschool.runescape.wiki/images/Dharok%27s_armour_equipped_male.png?3d05c'),
('Guthans Piece', 'https://oldschool.runescape.wiki/images/Guthan%27s_armour_equipped_male.png?89e79', 'https://oldschool.runescape.wiki/images/Guthan%27s_armour_equipped_male.png?89e79'),
('Karil Piece', 'https://oldschool.runescape.wiki/images/Karil%27s_armour_equipped_male.png?ed324', 'https://oldschool.runescape.wiki/images/Karil%27s_armour_equipped_male.png?ed324'),
('Torag Piece', 'https://oldschool.runescape.wiki/w/Torag_the_Corrupted%27s_equipment', 'https://oldschool.runescape.wiki/images/Torag%27s_armour_equipped_male.png?a73af'),
('Verac Piece', 'https://oldschool.runescape.wiki/w/Verac_the_Defiled%27s_equipment', 'https://oldschool.runescape.wiki/images/Verac%27s_armour_equipped_female.png?644b5');

-- Best-effort backfill: link historical bounties to a bounty_targets row where the
-- pre-migration freeform item_name is an exact or substring match. item_name is untouched
-- either way. Only applies where exactly one bounty_targets row matches, to avoid an
-- arbitrary pick among several candidates (e.g. short/generic names like "Any ...").
UPDATE public.bounties b
SET bounty_target_id = m.id
FROM (
    SELECT bounty_id, id
    FROM (
        SELECT b2.id AS bounty_id, t.id,
               count(*) OVER (PARTITION BY b2.id) AS match_count
        FROM public.bounties b2
        JOIN public.bounty_targets t
          ON lower(b2.item_name) = lower(t.bounty_name)
          OR lower(t.bounty_name) LIKE '%' || lower(b2.item_name) || '%'
          OR lower(b2.item_name) LIKE '%' || lower(t.bounty_name) || '%'
    ) matches
    WHERE match_count = 1
) m
WHERE b.id = m.bounty_id
  AND b.bounty_target_id IS NULL;

-- Manual fixups for historical names that don't share a substring with their closest
-- bounty_targets equivalent (chestplate/piece -> Armour wording, seed/scarf wording).
UPDATE public.bounties SET bounty_target_id = (SELECT id FROM public.bounty_targets WHERE bounty_name = 'Armadyl Armour')
WHERE item_name = 'Armadyl chestplate' AND bounty_target_id IS NULL;

UPDATE public.bounties SET bounty_target_id = (SELECT id FROM public.bounty_targets WHERE bounty_name = 'Bandos Armour')
WHERE item_name = 'Bandos chestplate' AND bounty_target_id IS NULL;

UPDATE public.bounties SET bounty_target_id = (SELECT id FROM public.bounty_targets WHERE bounty_name = 'Blue Moon Armour')
WHERE item_name = 'Blue moon chestplate' AND bounty_target_id IS NULL;

UPDATE public.bounties SET bounty_target_id = (SELECT id FROM public.bounty_targets WHERE bounty_name = 'Gauntlet Weapon Seed / Armour Seed')
WHERE item_name = 'Crystal armour seed' AND bounty_target_id IS NULL;

-- 'Gnome scarf' has no textual overlap with any new-list name; confirmed with the team that
-- 'Gnome Restaurant Clog Item' is its intended replacement/equivalent.
UPDATE public.bounties SET bounty_target_id = (SELECT id FROM public.bounty_targets WHERE bounty_name = 'Gnome Restaurant Clog Item')
WHERE item_name = 'Gnome scarf' AND bounty_target_id IS NULL;

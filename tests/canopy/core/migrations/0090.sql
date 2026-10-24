-- sha256 of 0090_tick_overseer_ran.sql: 7eb6b0f2aef4babe440d62a0208a9b1e21cf6faf1c43f59f5456d396a999001e

UPDATE ticks SET overseer_ran = 0 WHERE id = (SELECT min(id) FROM ticks);

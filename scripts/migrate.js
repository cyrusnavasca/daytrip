#!/usr/bin/env node
/**
 * Run: node scripts/migrate.js
 * Applies schema.sql against DATABASE_URL.
 */
const { Pool } = require("pg");
const fs = require("fs");
const path = require("path");

async function migrate() {
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) {
    console.error("Error: DATABASE_URL is not set");
    process.exit(1);
  }

  const pool = new Pool({
    connectionString,
    ssl:
      process.env.NODE_ENV === "production"
        ? { rejectUnauthorized: false }
        : false,
  });

  const sql = fs.readFileSync(path.join(__dirname, "schema.sql"), "utf8");

  const client = await pool.connect();
  try {
    console.log("Running migration...");
    await client.query(sql);
    console.log("Migration complete.");
  } catch (err) {
    console.error("Migration failed:", err.message);
    process.exit(1);
  } finally {
    client.release();
    await pool.end();
  }
}

migrate();

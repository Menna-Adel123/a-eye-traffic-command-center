const fs = require('fs');
const { execSync } = require('child_process');

const envFile = fs.readFileSync('backend/.env', 'utf-8');
const lines = envFile.split('\n');

for (const line of lines) {
  if (!line || line.startsWith('#') || !line.includes('=')) continue;
  
  const equalsIdx = line.indexOf('=');
  const key = line.slice(0, equalsIdx).trim();
  let value = line.slice(equalsIdx + 1).trim();
  
  // Remove surrounding quotes
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
    value = value.slice(1, -1);
  }

  console.log(`Adding ${key} to Vercel...`);
  try {
    // Add to production
    execSync(`npx vercel env add ${key} production --value "${value}" --yes`);
    // Add to preview
    execSync(`npx vercel env add ${key} preview --value "${value}" --yes`);
    // Add to development
    execSync(`npx vercel env add ${key} development --value "${value}" --yes`);
    console.log(`Successfully added ${key}`);
  } catch (err) {
    console.error(`Failed to add ${key}:`, err.message);
  }
}

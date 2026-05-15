const { PrismaClient } = require('@prisma/client');
const prisma = new PrismaClient();

async function main() {
  const incidents = await prisma.incident.findMany();
  console.log(`Total incidents in database: ${incidents.length}`);
  const pending = incidents.filter(i => i.status === 'pending' || i.status === 'emergency');
  console.log(`Pending/Emergency incidents: ${pending.length}`);
}

main()
  .catch(e => console.error(e))
  .finally(async () => await prisma.$disconnect());

const prisma = require('../prismaClient');

async function check() {
  const incidentCount = await prisma.incident.count();
  const userCount = await prisma.user.count();
  console.log(`Incidents: ${incidentCount}`);
  console.log(`Users: ${userCount}`);
  process.exit(0);
}

check();

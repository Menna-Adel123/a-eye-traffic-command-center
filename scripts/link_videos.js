const { PrismaClient } = require('@prisma/client');
const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '../backend/.env') });

const prisma = new PrismaClient();

const videos = [
    'https://akskeodbafacplvgwqip.supabase.co/storage/v1/object/public/aeye-uploads/accident1.mp4',
    'https://akskeodbafacplvgwqip.supabase.co/storage/v1/object/public/aeye-uploads/accident2.mp4',
    'https://akskeodbafacplvgwqip.supabase.co/storage/v1/object/public/aeye-uploads/accident3.mp4'
];

async function main() {
    console.log('Fetching top 3 pending/emergency incidents...');
    const incidents = await prisma.incident.findMany({
        where: {
            status: { in: ['pending', 'emergency'] }
        },
        take: 3,
        orderBy: { detectedAt: 'desc' }
    });

    if (incidents.length === 0) {
        console.log('No active incidents found to link videos to.');
        return;
    }

    for (let i = 0; i < incidents.length; i++) {
        if (videos[i]) {
            const updated = await prisma.incident.update({
                where: { id: incidents[i].id },
                data: { videoUrl: videos[i] }
            });
            console.log(`Linked ${videos[i]} to incident ${updated.incidentCode} (${updated.type})`);
        }
    }
}

main()
    .catch(e => {
        console.error(e);
        process.exit(1);
    })
    .finally(async () => {
        await prisma.$disconnect();
    });

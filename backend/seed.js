const prisma = require('./prismaClient');
const bcrypt = require('bcryptjs');

async function main() {
  // Clear existing
  await prisma.incident.deleteMany();
  await prisma.user.deleteMany();

  // Create User
  const passwordHash = await bcrypt.hash('admin123', 10);
  const user = await prisma.user.create({
    data: {
      serviceId: 'admin',
      passwordHash,
      name: 'Admin Officer',
      role: 'admin',
      station: 'Alexandria HQ',
    },
  });

  console.log('Created user:', user.serviceId);

  // Create incidents
  const now = new Date();
  const ago = (mins) => new Date(now.getTime() - mins * 60000);

  const incidents = [
    // Pending incidents (active, waiting for officer review)
    { incidentCode: 'EMG-001', type: 'Accident', severity: 'high', confidence: 82, locationName: 'Sidi Gaber', camera: 'Camera_12', latitude: 31.2156, longitude: 29.9553, status: 'pending', detectedAt: ago(8) },
    { incidentCode: 'EMG-002', type: 'Accident', severity: 'high', confidence: 91, locationName: 'Corniche Road', camera: 'Camera_07', latitude: 31.2100, longitude: 29.9100, status: 'pending', detectedAt: ago(5) },
    { incidentCode: 'EMG-003', type: 'Wrong-Way Driver', severity: 'high', confidence: 88, locationName: 'El-Horreya Road', camera: 'Camera_15', latitude: 31.2010, longitude: 29.9020, status: 'pending', detectedAt: ago(3) },
    { incidentCode: 'EMG-004', type: 'Pedestrian on Highway', severity: 'high', confidence: 79, locationName: 'International Coastal Road', camera: 'Camera_22', latitude: 31.2700, longitude: 30.0100, status: 'pending', detectedAt: ago(1) },
    { incidentCode: 'EMG-005', type: 'Traffic Jam', severity: 'medium', confidence: 68, locationName: 'Smouha', camera: 'Camera_09', latitude: 31.2190, longitude: 29.9520, status: 'pending', detectedAt: ago(12) },
    { incidentCode: 'EMG-006', type: 'Stalled Vehicle', severity: 'low', confidence: 72, locationName: 'Gleem', camera: 'Camera_04', latitude: 31.2270, longitude: 29.9480, status: 'pending', detectedAt: ago(20) },
    { incidentCode: 'EMG-007', type: 'Accident', severity: 'medium', confidence: 76, locationName: 'Moharam Bek', camera: 'Camera_18', latitude: 31.1960, longitude: 29.9150, status: 'pending', detectedAt: ago(2) },
    
    {
      incidentCode: 'EMG-008',
      type: 'Accident',
      severity: 'high',
      confidence: 79,
      locationName: 'Stanley Bridge',
      camera: 'Camera_03',
      latitude: 31.2150,
      longitude: 29.9400,
      status: 'pending',
      detectedAt: ago(6)
    },
    {
      incidentCode: 'EMG-009',
      type: 'Accident',
      severity: 'medium',
      confidence: 74,
      locationName: 'Smouha',
      camera: 'Camera_09',
      latitude: 31.2085,
      longitude: 29.9702,
      status: 'pending',
      detectedAt: ago(4)
    },
    {
      incidentCode: 'EMG-010',
      type: 'Accident',
      severity: 'high',
      confidence: 93,
      locationName: 'Miami',
      camera: 'Camera_18',
      latitude: 31.2301,
      longitude: 29.9805,
      status: 'pending',
      detectedAt: ago(2)
    },
    {
      incidentCode: 'EMG-011',
      type: 'Accident',
      severity: 'low',
      confidence: 68,
      locationName: 'Mandara',
      camera: 'Camera_21',
      latitude: 31.2330,
      longitude: 29.9900,
      status: 'pending',
      detectedAt: ago(7)
    },
    {
      incidentCode: 'EMG-012',
      type: 'Accident',
      severity: 'high',
      confidence: 85,
      locationName: 'Gleem',
      camera: 'Camera_11',
      latitude: 31.2205,
      longitude: 29.9508,
      status: 'pending',
      detectedAt: ago(1)
    },
    {
      incidentCode: 'EMG-021',
      type: 'Wrong-Way Driver',
      severity: 'high',
      confidence: 92,
      locationName: 'El-Agamy Road',
      camera: 'Camera_28',
      latitude: 31.1400,
      longitude: 29.8000,
      status: 'pending',
      detectedAt: ago(3)
    },
    {
      incidentCode: 'EMG-022',
      type: 'Stalled Vehicle',
      severity: 'low',
      confidence: 75,
      locationName: 'Dekheila',
      camera: 'Camera_31',
      latitude: 31.1600,
      longitude: 29.8300,
      status: 'pending',
      detectedAt: ago(15)
    },

    // Emergency (dispatched)
    { incidentCode: 'EMG-013', type: 'Traffic Jam', severity: 'medium', confidence: 74, locationName: 'Abu Qir St', camera: 'Camera_03', latitude: 31.2300, longitude: 29.9700, status: 'emergency', detectedAt: ago(45), dispatchedAt: ago(40), responseTimeMins: 5.4 },
    { incidentCode: 'EMG-014', type: 'Accident', severity: 'high', confidence: 95, locationName: 'Stanley Bridge', camera: 'Camera_20', latitude: 31.2395, longitude: 29.9710, status: 'emergency', detectedAt: ago(30), dispatchedAt: ago(27), responseTimeMins: 3.1 },
    { incidentCode: 'EMG-015', type: 'Road Hazard', severity: 'medium', confidence: 81, locationName: 'El-Mandara', camera: 'Camera_11', latitude: 31.2600, longitude: 30.0000, status: 'emergency', detectedAt: ago(60), dispatchedAt: ago(55), responseTimeMins: 4.8 },

    // False alerts
    { incidentCode: 'EMG-016', type: 'Accident', severity: 'low', confidence: 42, locationName: 'Kafr Abdo', camera: 'Camera_05', latitude: 31.2180, longitude: 29.9430, status: 'false-alert', detectedAt: ago(120), resolvedAt: ago(110), reviewNotes: 'Shadow mistaken for vehicle collision', reviewedBy: 'admin' },
    { incidentCode: 'EMG-017', type: 'Traffic Jam', severity: 'low', confidence: 38, locationName: 'Sporting', camera: 'Camera_14', latitude: 31.2090, longitude: 29.9340, status: 'false-alert', detectedAt: ago(90), resolvedAt: ago(85), reviewNotes: 'Construction zone, not a real jam', reviewedBy: 'admin' },

    // Resolved
    { incidentCode: 'EMG-018', type: 'Accident', severity: 'high', confidence: 93, locationName: 'Raml Station', camera: 'Camera_01', latitude: 31.2005, longitude: 29.9005, status: 'resolved', detectedAt: ago(180), dispatchedAt: ago(176), resolvedAt: ago(140), responseTimeMins: 2.8, reviewNotes: 'Ambulance arrived, injuries treated on site', reviewedBy: 'admin' },
    { incidentCode: 'EMG-019', type: 'Stalled Vehicle', severity: 'low', confidence: 85, locationName: 'Montaza', camera: 'Camera_25', latitude: 31.2870, longitude: 30.0200, status: 'resolved', detectedAt: ago(200), dispatchedAt: ago(195), resolvedAt: ago(170), responseTimeMins: 6.2, reviewNotes: 'Tow truck dispatched', reviewedBy: 'admin' },
    { incidentCode: 'EMG-020', type: 'Wrong-Way Driver', severity: 'high', confidence: 90, locationName: 'El-Max', camera: 'Camera_30', latitude: 31.1700, longitude: 29.8600, status: 'resolved', detectedAt: ago(300), dispatchedAt: ago(297), resolvedAt: ago(270), responseTimeMins: 1.9, reviewNotes: 'Police intercepted the vehicle', reviewedBy: 'admin' },
  ];


  for (const inc of incidents) {
    await prisma.incident.create({ data: inc });
  }

  console.log('Created incidents');
}

main()
  .catch(e => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });

export function getDailyTrafficDisplay(record) {
  if (!record) {
    return {
      value: 'Unavailable',
      date: 'No source data available',
      source: 'Source: Unavailable',
    };
  }

  const source = record.source || 'IMF PortWatch';
  return {
    value: `${record.tankers ?? 0} tankers/day`,
    date: `${source} data as of ${record.date}`,
    source: `Source: ${source} daily tanker transits`,
  };
}

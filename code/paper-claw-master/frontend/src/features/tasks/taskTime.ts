const MINUTES_PER_DAY = 24 * 60;

export function utcTimeToLocalTime(utcTime: string, offsetMinutes = -new Date().getTimezoneOffset()): string {
  return minutesToTime(timeToMinutes(utcTime) + offsetMinutes);
}

export function localTimeToUtcTime(localTime: string, offsetMinutes = -new Date().getTimezoneOffset()): string {
  return minutesToTime(timeToMinutes(localTime) - offsetMinutes);
}

function timeToMinutes(value: string): number {
  const [hours = '0', minutes = '0'] = value.split(':');
  return Number(hours) * 60 + Number(minutes);
}

function minutesToTime(value: number): string {
  const normalized = ((value % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
  const hours = Math.floor(normalized / 60);
  const minutes = normalized % 60;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

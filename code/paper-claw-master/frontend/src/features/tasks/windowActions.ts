export function windowRerunActionLabel(status: string): string | null {
  if (status === 'failed') {
    return 'Retry window';
  }
  if (status === 'succeeded') {
    return 'Recheck window';
  }
  return null;
}

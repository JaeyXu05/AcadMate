import api from './axios';

export async function dislikeAdvisor(advisorId: string): Promise<void> {
  await api.post('/feedback', { advisor_id: advisorId, feedback: 'dislike' });
}

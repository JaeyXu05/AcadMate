import MentorCard from './MentorCard';
import type { Advisor } from '../types/search';

interface AdvisorCardProps {
  advisor: Advisor;
  compact?: boolean;
  featured?: boolean;
  onDislike?: (advisorId: string) => void;
}

function AdvisorCard(props: AdvisorCardProps) {
  return <MentorCard {...props} />;
}

export default AdvisorCard;

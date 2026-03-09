import { redirect } from 'next/navigation';

export default function ChartsRedirectPage() {
  redirect('/analytics?tab=charts');
}

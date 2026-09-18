import type { Metadata } from 'next'
import { Inter, Sora } from 'next/font/google'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })
const sora = Sora({ subsets: ['latin'], weight: ['500', '600', '700'], variable: '--font-display' })

export const metadata: Metadata = {
  title: 'Lumina — drone show compiler',
  description: 'Author artwork. Compile physically valid swarm trajectories.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} ${sora.variable} h-full overflow-hidden`}>{children}</body>
    </html>
  )
}

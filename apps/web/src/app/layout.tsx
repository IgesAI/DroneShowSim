import type { Metadata } from 'next'
import { IBM_Plex_Mono, Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({ subsets: ['latin'], variable: '--font-ui' })
const mono = IBM_Plex_Mono({ subsets: ['latin'], weight: ['400', '500'], variable: '--font-mono' })

export const metadata: Metadata = {
  title: 'Lumina',
  description: 'Author, compile, and validate drone-show trajectories.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${inter.variable} ${mono.variable} h-full overflow-hidden font-sans`}>{children}</body>
    </html>
  )
}

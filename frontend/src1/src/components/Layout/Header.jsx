import React from 'react'
import { Box, Typography } from '@mui/material'
import { useApp } from '../../context/AppContext'

const Header = () => {
  const { selectedPipeline } = useApp()

  const getPipelineName = () => {
    switch (selectedPipeline) {
      case 'ey':
        return 'EY - International GAAP'
      case 'pwc':
        return 'PwC Manual'
      case 'ifrs':
        return 'IFRS (A + B + C)'
      case 'combined':
        return 'Combined (EY + PwC)'
      default:
        return 'Document Processing'
    }
  }

  return (
    <Box sx={{ mb: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Document Management Dashboard
      </Typography>
      <Typography variant="h6" color="text.secondary">
        {getPipelineName()}
      </Typography>
    </Box>
  )
}

export default Header

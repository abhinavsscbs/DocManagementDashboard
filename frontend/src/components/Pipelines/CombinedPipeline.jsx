import React from 'react'
import { Paper, Typography, Alert } from '@mui/material'

const CombinedPipeline = () => {
  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        Combined Pipeline (EY + PwC)
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Process EY and PwC documents together into a single FAISS index
      </Typography>

      <Alert severity="info">
        Combined pipeline UI coming soon. This will merge EY and PwC documents
        into a single searchable index.
      </Alert>
    </Paper>
  )
}

export default CombinedPipeline

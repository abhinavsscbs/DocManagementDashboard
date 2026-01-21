import React from 'react'
import {
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  Divider,
} from '@mui/material'
import DescriptionIcon from '@mui/icons-material/Description'
import FolderIcon from '@mui/icons-material/Folder'
import { useApp } from '../../context/AppContext'

const drawerWidth = 280

const Sidebar = () => {
  const { selectedPipeline, setSelectedPipeline } = useApp()

  const pipelines = [
    { id: 'ey', label: 'EY - International GAAP', icon: <DescriptionIcon /> },
    { id: 'pwc', label: 'PwC Manual', icon: <DescriptionIcon /> },
    { id: 'ifrs', label: 'IFRS (A + B + C)', icon: <FolderIcon /> },
  ]

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: drawerWidth,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: drawerWidth,
          boxSizing: 'border-box',
        },
      }}
    >
      <Toolbar>
        <Typography variant="h6" noWrap component="div">
          Pipelines
        </Typography>
      </Toolbar>
      <Divider />
      <List>
        {pipelines.map((pipeline) => (
          <ListItem key={pipeline.id} disablePadding>
            <ListItemButton
              selected={selectedPipeline === pipeline.id}
              onClick={() => setSelectedPipeline(pipeline.id)}
            >
              <ListItemIcon>{pipeline.icon}</ListItemIcon>
              <ListItemText primary={pipeline.label} />
            </ListItemButton>
          </ListItem>
        ))}
      </List>
    </Drawer>
  )
}

export default Sidebar

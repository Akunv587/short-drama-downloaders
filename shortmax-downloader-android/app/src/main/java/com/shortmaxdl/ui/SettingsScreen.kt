package com.shortmaxdl.ui

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.shortmaxdl.domain.model.VideoQuality
import kotlinx.coroutines.launch

private const val FFMPEG_VERSION = "6.0 (ffmpeg-kit-min)"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    viewModel: MainViewModel,
    onBack: () -> Unit,
    onNavigateToLogin: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsState()
    val scope = rememberCoroutineScope()
    var showProxyDialog by remember { mutableStateOf(false) }
    var proxyInput by remember { mutableStateOf("") }

    // Folder picker
    val folderPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocumentTree()
    ) { uri: Uri? ->
        uri?.let {
            // Convert content URI to readable path
            val path = uri.toString()
            // Try to get actual filesystem path
            val docId = DocumentsContract.getTreeDocumentId(uri)
            val split = docId.split(":")
            val realPath = if (split.size >= 2) {
                "/storage/${split[0]}/${split[1]}"
            } else {
                path
            }
            viewModel.updateDownloadPath(realPath)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("设置") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                )
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            // Download Path
            ListItem(
                headlineContent = { Text("下载路径") },
                supportingContent = { Text(uiState.downloadPath, maxLines = 1) },
                leadingContent = {
                    Icon(Icons.Default.Folder, contentDescription = null)
                },
                trailingContent = {
                    TextButton(onClick = { folderPickerLauncher.launch(null) }) {
                        Text("更改")
                    }
                }
            )

            HorizontalDivider()

            // Quality
            ListItem(
                headlineContent = { Text("默认画质") },
                leadingContent = {
                    Icon(Icons.Default.HighQuality, contentDescription = null)
                },
                trailingContent = {
                    Row {
                        VideoQuality.entries.forEach { q ->
                            FilterChip(
                                selected = q == uiState.videoQuality,
                                onClick = { viewModel.updateQuality(q) },
                                label = { Text(q.label) },
                                modifier = Modifier.padding(horizontal = 2.dp),
                            )
                        }
                    }
                }
            )

            HorizontalDivider()

            // Proxy
            ListItem(
                headlineContent = { Text("HTTP 代理") },
                supportingContent = {
                    Text(
                        if (uiState.proxyUrl.isNotBlank()) uiState.proxyUrl
                        else "未设置 — 用于访问被墙的网站（如 shorttv.live）"
                    )
                },
                leadingContent = {
                    Icon(Icons.Default.VpnKey, contentDescription = null)
                },
                trailingContent = {
                    TextButton(onClick = { showProxyDialog = true }) {
                        Text("设置")
                    }
                }
            )

            HorizontalDivider()

            // VIP Login
            ListItem(
                headlineContent = { Text("VIP 登录") },
                supportingContent = {
                    Text(if (uiState.isLoggedIn) "已登录" else "未登录")
                },
                leadingContent = {
                    Icon(
                        if (uiState.isLoggedIn) Icons.Default.VerifiedUser
                        else Icons.Default.Lock,
                        contentDescription = null,
                    )
                },
                trailingContent = {
                    if (uiState.isLoggedIn) {
                        TextButton(onClick = {
                            viewModel.logout()
                        }) {
                            Text("退出登录", color = MaterialTheme.colorScheme.error)
                        }
                    } else {
                        TextButton(onClick = onNavigateToLogin) {
                            Text("去登录")
                        }
                    }
                }
            )

            HorizontalDivider()

            // Info
            ListItem(
                headlineContent = { Text("版本") },
                supportingContent = { Text("ShortMax DL v1.0.0") },
                leadingContent = {
                    Icon(Icons.Default.Info, contentDescription = null)
                },
            )

            HorizontalDivider()

            // FFmpeg version
            ListItem(
                headlineContent = { Text("ffmpeg 版本") },
                supportingContent = { Text(FFMPEG_VERSION) },
                leadingContent = {
                    Icon(Icons.Default.Code, contentDescription = null)
                },
            )

            HorizontalDivider()

            // Clear cache
            ListItem(
                headlineContent = { Text("清理缓存") },
                supportingContent = { Text("删除所有下载历史记录") },
                leadingContent = {
                    Icon(Icons.Default.DeleteSweep, contentDescription = null)
                },
                trailingContent = {
                    TextButton(
                        onClick = {
                            viewModel.clearCache()
                        }
                    ) {
                        Text("立即清理", color = MaterialTheme.colorScheme.error)
                    }
                },
            )
        }
    }

    // Proxy dialog
    if (showProxyDialog) {
        AlertDialog(
            onDismissRequest = { showProxyDialog = false },
            title = { Text("设置 HTTP 代理") },
            text = {
                OutlinedTextField(
                    value = proxyInput,
                    onValueChange = { proxyInput = it },
                    label = { Text("代理地址") },
                    placeholder = { Text("http://127.0.0.1:10808") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
            },
            confirmButton = {
                Button(onClick = {
                    scope.launch {
                        viewModel.updateProxy(proxyInput)
                    }
                    showProxyDialog = false
                }) {
                    Text("保存")
                }
            },
            dismissButton = {
                TextButton(onClick = { showProxyDialog = false }) {
                    Text("取消")
                }
            }
        )
    }
}

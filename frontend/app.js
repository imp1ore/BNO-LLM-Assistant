// API Configuration – use same origin when frontend is served by API server (e.g. Docker/production)
const API_BASE_URL = (typeof window !== 'undefined' && window.location.origin)
  ? `${window.location.origin}/api`
  : 'http://127.0.0.1:9000/api';

// Global state
let currentUser = null;
let currentChatId = null;
let authToken = localStorage.getItem('authToken');
let userCanUpload = false;
let userIsAdmin = false;
let lastActivityTime = Date.now();
let sessionTimeoutId = null;
const SESSION_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes in milliseconds

// Upload limit (kept in sync with the server via /api/config; fallback below)
let maxUploadMb = 100;
let allowedExtensions = [
    '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.txt', '.md',
    '.rtf', '.csv', '.html', '.png', '.jpg', '.jpeg', '.gif',
];
let docPollTimer = null;

function formatAllowedTypesHint(exts) {
    if (!exts || !exts.length) return 'PDF, DOC, DOCX, PPTX, XLS, XLSX, TXT, and more';
    const labels = exts.map((ext) => ext.replace(/^\./, '').toUpperCase());
    if (labels.length <= 12) return labels.join(', ');
    return `${labels.slice(0, 12).join(', ')}, and ${labels.length - 12} more`;
}

function applyClientConfig(cfg) {
    if (!cfg) return;
    if (cfg.max_file_size_mb) {
        maxUploadMb = cfg.max_file_size_mb;
        const hint = document.getElementById('maxFileSizeHint');
        if (hint) hint.textContent = `${maxUploadMb}MB`;
    }
    if (Array.isArray(cfg.allowed_extensions) && cfg.allowed_extensions.length) {
        allowedExtensions = cfg.allowed_extensions;
        const fileInput = document.getElementById('fileInput');
        if (fileInput) fileInput.accept = allowedExtensions.join(',');
        const typesHint = document.getElementById('allowedTypesHint');
        if (typesHint) typesHint.textContent = formatAllowedTypesHint(allowedExtensions);
    }
}

async function loadClientConfig() {
    try {
        const resp = await fetch(`${API_BASE_URL}/config`);
        if (resp.ok) {
            const cfg = await resp.json();
            applyClientConfig(cfg);
        }
    } catch (e) {
        console.warn('Could not load client config; using default limit', e);
        applyClientConfig({ allowed_extensions: allowedExtensions, max_file_size_mb: maxUploadMb });
    }
}

// Refresh the documents list a few times while any document is still processing,
// so background-indexed uploads flip from "Processing" to "Indexed" automatically.
function pollDocumentsWhileProcessing(attempts = 40) {
    if (docPollTimer) clearTimeout(docPollTimer);
    const tick = async (left) => {
        const docsScreen = document.getElementById('documentsScreen');
        if (!docsScreen || docsScreen.style.display === 'none' || left <= 0) return;
        await loadDocuments();
        docPollTimer = setTimeout(() => tick(left - 1), 3000);
    };
    tick(attempts);
}

// ============================================================================
// Global Functions (accessible from HTML onclick)
// ============================================================================
// Create User function - must be defined before DOMContentLoaded
async function createUser() {
    console.log('createUser called'); // Debug log
    if (!userIsAdmin) {
        showNotification('Admin access required', 'error');
        return;
    }
    
    const usernameEl = document.getElementById('newUserUsername');
    const passwordEl = document.getElementById('newUserPassword');
    const fullNameEl = document.getElementById('newUserFullName');
    const canUploadEl = document.getElementById('newUserCanUpload');
    const isAdminEl = document.getElementById('newUserIsAdmin');
    
    if (!usernameEl || !passwordEl) {
        console.error('Form elements not found');
        showNotification('Form elements not found. Please refresh the page.', 'error');
        return;
    }
    
    const username = usernameEl.value?.trim();
    const password = passwordEl.value;
    const fullName = fullNameEl?.value?.trim();
    const canUpload = canUploadEl?.checked || false;
    const isAdmin = isAdminEl?.checked || false;
    
    // Validation
    if (!username || !password) {
        showNotification('Username and password are required', 'error');
        return;
    }
    
    if (username.length < 3) {
        showNotification('Username must be at least 3 characters', 'error');
        return;
    }
    
    if (password.length < 3) {
        showNotification('Password must be at least 3 characters', 'error');
        return;
    }
    
    try {
        console.log('Sending request to create user:', { username, canUpload, isAdmin });
        const response = await secureFetch(`${API_BASE_URL}/admin/users`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: username,
                password: password,
                full_name: fullName || null,
                can_upload: canUpload,
                is_admin: isAdmin
            })
        });
        
        if (response.ok) {
            const newUser = await response.json();
            showNotification(`User "${newUser.username}" created successfully!`, 'success');
            
            // Clear form
            usernameEl.value = '';
            passwordEl.value = '';
            if (fullNameEl) fullNameEl.value = '';
            if (canUploadEl) canUploadEl.checked = false;
            if (isAdminEl) isAdminEl.checked = false;
            
            // Reload users list
            loadUsers();
        } else {
            const errorData = await response.json().catch(() => ({ detail: 'Failed to create user' }));
            console.error('Error response:', errorData);
            showNotification(errorData.detail || 'Failed to create user', 'error');
        }
    } catch (error) {
        console.error('Error creating user:', error);
        showNotification('Error creating user. Please try again.', 'error');
    }
}

// Make it globally accessible
window.createUser = createUser;

// ============================================================================
// Change Password (self-service)
// ============================================================================
function openChangePassword() {
    const modal = document.getElementById('changePasswordModal');
    if (!modal) return;
    const err = document.getElementById('cpError');
    if (err) { err.style.display = 'none'; err.textContent = ''; }
    ['cpOldPassword', 'cpNewPassword', 'cpConfirmPassword'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    modal.classList.add('active');
}
window.openChangePassword = openChangePassword;

function closeChangePassword() {
    const modal = document.getElementById('changePasswordModal');
    if (modal) modal.classList.remove('active');
}
window.closeChangePassword = closeChangePassword;

async function submitChangePassword() {
    const oldPassword = document.getElementById('cpOldPassword')?.value || '';
    const newPassword = document.getElementById('cpNewPassword')?.value || '';
    const confirmPassword = document.getElementById('cpConfirmPassword')?.value || '';
    const err = document.getElementById('cpError');
    const btn = document.getElementById('cpSubmitBtn');

    const showErr = (msg) => {
        if (err) { err.textContent = msg; err.style.display = 'block'; }
    };

    if (!oldPassword || !newPassword) {
        showErr('Please fill in all fields.');
        return;
    }
    if (newPassword !== confirmPassword) {
        showErr('New passwords do not match.');
        return;
    }

    if (btn) { btn.disabled = true; btn.textContent = 'Updating...'; }
    try {
        const response = await secureFetch(`${API_BASE_URL}/auth/change-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })
        });
        if (response.ok) {
            closeChangePassword();
            showNotification('Password changed successfully.', 'success');
        } else {
            const data = await response.json().catch(() => ({ detail: 'Failed to change password' }));
            showErr(data.detail || 'Failed to change password.');
        }
    } catch (error) {
        console.error('Error changing password:', error);
        showErr('Connection error. Please try again.');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Update Password'; }
    }
}
window.submitChangePassword = submitChangePassword;

// ============================================================================
// Session Management (Enterprise Standard)
// ============================================================================
function setupActivityTracking() {
    // Track user activity to reset session timeout
    const events = ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart', 'click'];
    events.forEach(event => {
        document.addEventListener(event, resetActivityTimer, true);
    });
}

function resetActivityTimer() {
    lastActivityTime = Date.now();
    
    // Clear existing timeout
    if (sessionTimeoutId) {
        clearTimeout(sessionTimeoutId);
    }
    
    // Only set timeout if user is logged in
    if (authToken) {
        sessionTimeoutId = setTimeout(() => {
            // Check if user is still inactive
            const inactiveTime = Date.now() - lastActivityTime;
            if (inactiveTime >= SESSION_TIMEOUT_MS) {
                logout('Your session has expired due to inactivity. Please login again.');
            } else {
                // Reset timer with remaining time
                resetActivityTimer();
            }
        }, SESSION_TIMEOUT_MS);
    }
}

// ============================================================================
// Initialization
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
    const loginScreen = document.getElementById('loginScreen');
    const authLoading = document.getElementById('authLoading');
    const chatScreen = document.getElementById('chatScreen');

    // Load public client config (upload limit, allowed types)
    loadClientConfig();

    // Enterprise standard: Always validate token on page load
    if (authToken) {
        // Hide login screen immediately, show loading
        if (loginScreen) loginScreen.classList.add('hidden');
        if (authLoading) authLoading.classList.remove('hidden');
        if (chatScreen) chatScreen.style.display = 'none';
        // Check authentication (will validate token and show login if expired)
        checkAuth();
    } else {
        // No token, show login screen (enterprise standard - always require login)
        if (loginScreen) loginScreen.classList.remove('hidden');
        if (authLoading) authLoading.classList.add('hidden');
        if (chatScreen) chatScreen.style.display = 'none';
    }
    
    // Set up activity tracking for session timeout
    setupActivityTracking();
    
    // Setup drag and drop for file uploads
    setupDragAndDrop();
    
    // Login form handler
    document.getElementById('loginForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        await handleLogin();
    });
    
    
    // Enable send button when input has text
    const messageInput = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    if (messageInput && sendBtn) {
        messageInput.addEventListener('input', () => {
            sendBtn.disabled = !messageInput.value.trim();
            // Auto-resize textarea
            messageInput.style.height = 'auto';
            messageInput.style.height = Math.min(messageInput.scrollHeight, 200) + 'px';
        });
        
        // Send on Enter (Shift+Enter for new line)
        messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (!sendBtn.disabled) {
                    sendMessage();
                }
            }
        });
    }
});

// ============================================================================
// Drag and Drop File Upload
// ============================================================================
function setupDragAndDrop() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    
    if (!uploadArea || !fileInput) return;
    
    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    // Highlight drop area when item is dragged over it
    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => {
            if (userCanUpload) {
                uploadArea.classList.add('dragover');
            }
        }, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => {
            uploadArea.classList.remove('dragover');
        }, false);
    });
    
    // Handle dropped files
    uploadArea.addEventListener('drop', (e) => {
        if (!userCanUpload) {
            showNotification('You do not have permission to upload documents.', 'error');
            return;
        }
        
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            processFiles(files);
        }
    }, false);
}

// ============================================================================
// Authentication
// ============================================================================
async function checkAuth() {
    try {
        const response = await secureFetch(`${API_BASE_URL}/auth/me`);
        if (response.ok) {
            currentUser = await response.json();
            userCanUpload = currentUser.can_upload || currentUser.is_admin;
            userIsAdmin = currentUser.is_admin;
            
            // Show/hide admin button based on admin status
            const adminBtn = document.getElementById('btnAdmin');
            if (adminBtn) {
                adminBtn.style.display = userIsAdmin ? 'block' : 'none';
            }
            
            // Show/hide documents button based on upload permission
            const documentsBtn = document.getElementById('btnDocuments');
            if (documentsBtn) {
                documentsBtn.style.display = userCanUpload ? 'block' : 'none';
            }
            
            // Hide admin screen if user is not admin
            if (!userIsAdmin) {
                const adminScreen = document.getElementById('adminScreen');
                if (adminScreen) {
                    adminScreen.style.display = 'none';
                }
            }
            
            // Hide documents screen if user cannot upload
            if (!userCanUpload) {
                const documentsScreen = document.getElementById('documentsScreen');
                if (documentsScreen) {
                    documentsScreen.style.display = 'none';
                }
            }
            
            // Update username display in all locations
            const userName = document.getElementById('userName');
            const userNameDocs = document.getElementById('userNameDocs');
            const userNameAdmin = document.getElementById('userNameAdmin');
            
            if (currentUser) {
                // Use full_name if set and not empty, otherwise username, never show ID
                const displayName = (currentUser.full_name && currentUser.full_name.trim()) || currentUser.username || 'User';
                console.log('[checkAuth] Setting display name to:', displayName, 'for user:', currentUser.username);
                
                if (userName) {
                    userName.textContent = displayName;
                    console.log('[checkAuth] Updated userName element to:', userName.textContent);
                }
                if (userNameDocs) userNameDocs.textContent = displayName;
                if (userNameAdmin) userNameAdmin.textContent = displayName;
            }
            
            // Hide loading, show chat screen
            const authLoading = document.getElementById('authLoading');
            if (authLoading) authLoading.classList.add('hidden');
            showChatScreen();
            loadChats();
            
            // Reset activity timer and start session timeout
            resetActivityTimer();
        } else if (response.status === 401) {
            // Token expired or invalid - clear and show login (enterprise standard)
            logout('Your session has expired. Please login again.');
        } else {
            // Other error - show login screen
            logout('Authentication check failed. Please login again.');
        }
    } catch (error) {
        // Network error or other exception
        console.error('Auth check error:', error);
        logout('Connection error. Please check your connection and try again.');
    }
}

function handleAuthFailure(message) {
    // Clear invalid token
    localStorage.removeItem('authToken');
    authToken = null;
    currentUser = null;
    
    // Clear session timeout
    if (sessionTimeoutId) {
        clearTimeout(sessionTimeoutId);
        sessionTimeoutId = null;
    }
    
    // Show login screen
    const loginScreen = document.getElementById('loginScreen');
    const authLoading = document.getElementById('authLoading');
    const chatScreen = document.getElementById('chatScreen');
    
    if (loginScreen) loginScreen.classList.remove('hidden');
    if (authLoading) authLoading.classList.add('hidden');
    if (chatScreen) chatScreen.style.display = 'none';
    
    // Show error message if provided
    if (message) {
        const errorEl = document.getElementById('loginError');
        if (errorEl) {
            errorEl.textContent = message;
            errorEl.style.display = 'block';
        }
    }
}

async function handleLogin() {
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const errorEl = document.getElementById('loginError');
    const loginBtn = document.getElementById('loginBtn');

    errorEl.style.display = 'none';
    loginBtn.disabled = true;
    loginBtn.textContent = 'Signing in...';

    try {
        const response = await fetch(`${API_BASE_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });

        if (response.ok) {
            const data = await response.json();
            authToken = data.access_token;
            localStorage.setItem('authToken', authToken);
            
            // Set user from response if available, otherwise load it
            if (data.user) {
                currentUser = data.user;
                userCanUpload = data.user.can_upload || data.user.is_admin;
                userIsAdmin = data.user.is_admin;
                
                // Update username display in all locations - use full_name if available, otherwise username
                const userName = document.getElementById('userName');
                const userNameDocs = document.getElementById('userNameDocs');
                const userNameAdmin = document.getElementById('userNameAdmin');
                
                // Use full_name if set and not empty, otherwise username, never show ID
                const displayName = (currentUser.full_name && currentUser.full_name.trim()) || currentUser.username || 'User';
                console.log('[handleLogin] Setting display name to:', displayName, 'for user:', currentUser.username);
                
                if (userName) {
                    userName.textContent = displayName;
                    console.log('[handleLogin] Updated userName element to:', userName.textContent);
                }
                if (userNameDocs) userNameDocs.textContent = displayName;
                if (userNameAdmin) userNameAdmin.textContent = displayName;
                
                // Update admin button visibility
                const adminBtn = document.getElementById('btnAdmin');
                if (adminBtn) {
                    adminBtn.style.display = userIsAdmin ? 'block' : 'none';
                }
                
                // Update documents button visibility
                const documentsBtn = document.getElementById('btnDocuments');
                if (documentsBtn) {
                    documentsBtn.style.display = userCanUpload ? 'block' : 'none';
                }
                
                // Hide admin screen if user is not admin (security)
                if (!userIsAdmin) {
                    const adminScreen = document.getElementById('adminScreen');
                    if (adminScreen) {
                        adminScreen.style.display = 'none';
                    }
                }
                
                // Hide documents screen if user cannot upload
                if (!userCanUpload) {
                    const documentsScreen = document.getElementById('documentsScreen');
                    if (documentsScreen) {
                        documentsScreen.style.display = 'none';
                    }
                }
            }
            
            // CRITICAL: Clear previous user's chat state before loading new user's chats
            currentChatId = null;
            
            // Clear chat list and messages immediately
            const chatList = document.getElementById('chatList');
            if (chatList) {
                chatList.innerHTML = '<div class="no-chats">Loading...</div>';
            }
            
            const messagesContainer = document.getElementById('messagesContainer');
            if (messagesContainer) {
                messagesContainer.innerHTML = '<div class="empty-state">Start a new conversation or select a chat from the sidebar</div>';
            }
            
            // Update UI
            showChatScreen();
            
            // Small delay to ensure UI is cleared before loading new chats
            setTimeout(() => {
                // Load chats for the NEW user (will be filtered by backend based on current_user.id)
                loadChats();
            }, 100);
            
            // Start session timeout tracking (enterprise standard)
            resetActivityTimer();
        } else {
            const errorData = await response.json().catch(() => ({ detail: 'Login failed' }));
            errorEl.textContent = errorData.detail || 'Login failed. Please check your credentials.';
            errorEl.style.display = 'block';
        }
    } catch (error) {
        errorEl.textContent = 'Connection error. Please check your connection and try again.';
        errorEl.style.display = 'block';
    } finally {
        loginBtn.disabled = false;
        loginBtn.textContent = 'Sign In';
    }
}

async function loadUserInfo() {
    if (!authToken) return;
    
    try {
        const response = await secureFetch(`${API_BASE_URL}/auth/me`);
        if (response.ok) {
            const userData = await response.json();
            currentUser = {
                ...userData,
                full_name: userData.full_name || userData.username,
                can_upload: userData.can_upload !== undefined ? userData.can_upload : true
            };
            const usernameDisplay = document.getElementById('usernameDisplay');
            if (usernameDisplay) {
                usernameDisplay.textContent = currentUser.full_name || currentUser.username;
            }
            userCanUpload = currentUser.can_upload || currentUser.is_admin;
            userIsAdmin = currentUser.is_admin;
        }
    } catch (error) {
        console.error('Error loading user info:', error);
    }
}

function handleLogout() {
    // Clear all state
    localStorage.removeItem('authToken');
    authToken = null;
    currentUser = null;
    currentChatId = null;
    userCanUpload = false;
    userIsAdmin = false;
    
    // Clear chat UI
    const chatList = document.getElementById('chatList');
    if (chatList) {
        chatList.innerHTML = '';
    }
    
    const messagesContainer = document.getElementById('messagesContainer');
    if (messagesContainer) {
        messagesContainer.innerHTML = '<div class="empty-state">Start a new conversation or select a chat from the sidebar</div>';
    }
    
    // Clear username displays
    const userName = document.getElementById('userName');
    const userNameDocs = document.getElementById('userNameDocs');
    const userNameAdmin = document.getElementById('userNameAdmin');
    if (userName) userName.textContent = '';
    if (userNameDocs) userNameDocs.textContent = '';
    if (userNameAdmin) userNameAdmin.textContent = '';
    
    showLoginScreen();
}

function showLoginScreen() {
    const loginScreen = document.getElementById('loginScreen');
    const chatScreen = document.getElementById('chatScreen');
    if (loginScreen) loginScreen.classList.remove('hidden');
    if (chatScreen) chatScreen.style.display = 'none';
}

function logout(message = 'You have been logged out.') {
    // Clear session
    localStorage.removeItem('authToken');
    authToken = null;
    currentUser = null;
    currentChatId = null;
    userCanUpload = false;
    userIsAdmin = false;
    
    // Clear session timeout
    if (sessionTimeoutId) {
        clearTimeout(sessionTimeoutId);
        sessionTimeoutId = null;
    }
    
    const loginScreen = document.getElementById('loginScreen');
    const authLoading = document.getElementById('authLoading');
    const chatScreen = document.getElementById('chatScreen');
    const documentsScreen = document.getElementById('documentsScreen');
    const adminScreen = document.getElementById('adminScreen');
    
    if (loginScreen) loginScreen.classList.remove('hidden');
    if (authLoading) authLoading.classList.add('hidden');
    if (chatScreen) chatScreen.style.display = 'none';
    if (documentsScreen) documentsScreen.style.display = 'none';
    if (adminScreen) adminScreen.style.display = 'none';
    
    // Show logout message
    const errorEl = document.getElementById('loginError');
    if (errorEl) {
        errorEl.textContent = message;
        errorEl.style.display = 'block';
    }
}

// ============================================================================
// Screen Management
// ============================================================================
function showChatScreen() {
    const chatScreen = document.getElementById('chatScreen');
    const documentsScreen = document.getElementById('documentsScreen');
    const adminScreen = document.getElementById('adminScreen');
    const loginScreen = document.getElementById('loginScreen');
    
    if (chatScreen) chatScreen.style.display = 'flex';
    if (documentsScreen) documentsScreen.style.display = 'none';
    if (adminScreen) adminScreen.style.display = 'none';
    if (loginScreen) loginScreen.classList.add('hidden');
    
    // Update username display when showing chat screen (ensure it's always current)
    if (currentUser) {
        const userName = document.getElementById('userName');
        const displayName = currentUser.full_name || currentUser.username || 'User';
        if (userName) {
            userName.textContent = displayName;
            console.log('[showChatScreen] Updated username display to:', displayName);
        }
    }
    
    // Update active nav button
    updateNavButtons('chat');
}

function showDocumentsScreen() {
    // Security check: Only allow users with upload permission to access documents screen
    if (!userCanUpload) {
        showNotification('Access denied. Upload permission required to view documents.', 'error');
        // Redirect to chat screen if no upload access
        showChatScreen();
        return;
    }
    
    const chatScreen = document.getElementById('chatScreen');
    const documentsScreen = document.getElementById('documentsScreen');
    const adminScreen = document.getElementById('adminScreen');
    
    if (chatScreen) chatScreen.style.display = 'none';
    if (documentsScreen) documentsScreen.style.display = 'block';
    // Always hide admin screen when switching to documents (security)
    if (adminScreen) adminScreen.style.display = 'none';
    
    loadDocuments();
    updateNavButtons('documents');
}

function showAdminScreen() {
    // Security check: Only allow admin users to access admin screen
    if (!userIsAdmin) {
        showNotification('Access denied. Admin privileges required.', 'error');
        // Redirect to chat screen if not admin
        showChatScreen();
        return;
    }
    
    const chatScreen = document.getElementById('chatScreen');
    const documentsScreen = document.getElementById('documentsScreen');
    const adminScreen = document.getElementById('adminScreen');
    
    if (chatScreen) chatScreen.style.display = 'none';
    if (documentsScreen) documentsScreen.style.display = 'none';
    if (adminScreen) adminScreen.style.display = 'block';
    
    loadUsers();
    updateNavButtons('admin');
}

function updateNavButtons(active) {
    const chatBtn = document.getElementById('btnChat');
    const docsBtn = document.getElementById('btnDocuments');
    const adminBtn = document.getElementById('btnAdmin');
    
    [chatBtn, docsBtn, adminBtn].forEach(btn => {
        if (btn) {
            btn.classList.remove('active');
        }
    });
    
    if (active === 'chat' && chatBtn) chatBtn.classList.add('active');
    if (active === 'documents' && docsBtn) docsBtn.classList.add('active');
    if (active === 'admin' && adminBtn && userIsAdmin) adminBtn.classList.add('active');
    
    // Security: Ensure admin button is only visible to admins
    if (adminBtn) {
        adminBtn.style.display = userIsAdmin ? 'block' : 'none';
    }
}

// ============================================================================
// Chat Functions
// ============================================================================
async function loadChats() {
    if (!authToken) {
        console.log('[loadChats] No auth token, skipping');
        return;
    }
    
    if (!currentUser) {
        console.log('[loadChats] No current user, skipping');
        return;
    }
    
    console.log('[loadChats] Loading chats for user:', currentUser.username, 'id:', currentUser.id);
    
    try {
        const response = await secureFetch(`${API_BASE_URL}/chats`);
        console.log('[loadChats] API response status:', response.status);
        
        if (response.ok) {
            const chats = await response.json();
            console.log('[loadChats] Loaded', chats.length, 'chats for user:', currentUser.username);
            console.log('[loadChats] Chat IDs:', chats.map(c => c.id));
            
            // CRITICAL: Do NOT clear currentChatId or messages container here
            // This function is called after sending messages, and we don't want to lose the conversation
            // Only clear if there's no active chat AND no messages in the container
            const messagesContainer = document.getElementById('messagesContainer');
            if (messagesContainer && !currentChatId) {
                // Only show empty state if container is actually empty (no messages)
                const hasMessages = messagesContainer.querySelectorAll('.message').length > 0;
                if (!hasMessages && !messagesContainer.querySelector('.empty-state')) {
                    messagesContainer.innerHTML = '<div class="empty-state">Start a new conversation or select a chat from the sidebar</div>';
                }
            }
            
            renderChats(chats);
        } else {
            const errorData = await response.json().catch(() => ({ detail: 'Failed to load chats' }));
            console.error('[loadChats] Error:', errorData);
            const chatList = document.getElementById('chatList');
            if (chatList) {
                chatList.innerHTML = '<div class="no-chats" style="color: red;">Error loading chats</div>';
            }
        }
    } catch (error) {
        console.error('[loadChats] Exception:', error);
        const chatList = document.getElementById('chatList');
        if (chatList) {
            chatList.innerHTML = '<div class="no-chats" style="color: red;">Error loading chats</div>';
        }
    }
}

function renderChats(chats) {
    const chatList = document.getElementById('chatList');
    if (!chatList) {
        console.error('ERROR: chatList element not found in DOM!');
        return;
    }
    
    console.log('Rendering chats:', chats);
    
    chatList.innerHTML = '';
    
    if (!chats || chats.length === 0) {
        chatList.innerHTML = '<div class="no-chats">No conversations yet.<br>Start a new chat to begin!</div>';
        return;
    }
    
    chats.forEach(chat => {
        const chatItem = document.createElement('div');
        chatItem.className = 'chat-item';
        chatItem.dataset.chatId = chat.id;
        
        // Generate title from first message if no title
        let title = chat.title;
        if (!title && chat.messages && chat.messages.length > 0) {
            const firstUserMessage = chat.messages.find(m => m.role === 'user');
            if (firstUserMessage) {
                title = firstUserMessage.content.substring(0, 50);
                if (firstUserMessage.content.length > 50) title += '...';
            }
        }
        if (!title) {
            title = `Chat ${chat.id}`;
        }
        
        chatItem.innerHTML = `
            <div class="chat-item-content">
                <div class="chat-item-title">${escapeHtml(title)}</div>
            </div>
            <div class="chat-item-actions">
                <button class="chat-delete-btn" onclick="deleteChat(${chat.id}, event)" title="Delete chat">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M3 6h18"></path>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"></path>
                        <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        `;
        
        chatItem.addEventListener('click', (e) => {
            if (!e.target.closest('.chat-delete-btn')) {
                loadChat(chat.id);
            }
        });
        
        chatList.appendChild(chatItem);
    });
}

function formatTime(dateString) {
    if (!dateString) return 'Unknown';
    
    try {
        // Parse the date string (handles ISO format from server)
        const date = new Date(dateString);
        
        // Check if date is valid
        if (isNaN(date.getTime())) {
            return 'Invalid date';
        }
        
        const now = new Date();
        const diffMs = now - date;
        
        // Handle negative differences (future dates) - shouldn't happen but just in case
        if (diffMs < 0) {
            return 'Just now';
        }
        
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);
        
        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;
        
        // For older dates, show formatted date
        return date.toLocaleDateString('en-US', { 
            month: 'short', 
            day: 'numeric', 
            year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
        });
    } catch (e) {
        console.error('Error formatting date:', e, dateString);
        return 'Invalid date';
    }
}

async function loadChat(chatId) {
    currentChatId = chatId;
    
    // Update active chat in UI
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.chatId == chatId) {
            item.classList.add('active');
        }
    });
    
    try {
        const response = await secureFetch(`${API_BASE_URL}/chats/${chatId}/messages`);
        if (response.ok) {
            const messages = await response.json();
            displayMessages(messages);
        }
    } catch (error) {
        console.error('Error loading chat:', error);
    }
}

function displayMessages(messages) {
    const messagesContainer = document.getElementById('messagesContainer');
    if (!messagesContainer) return;
    
    // Remove empty state if present
    const emptyState = messagesContainer.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    
    messagesContainer.innerHTML = '';
    
    messages.forEach(message => {
        addMessage(message.role, message.content, false);
    });
    
    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function addMessage(role, content, animate = true) {
    const messagesContainer = document.getElementById('messagesContainer');
    if (!messagesContainer) return;
    
    // Handle empty content
    if (!content || content.trim() === '') {
        content = role === 'assistant' 
            ? 'I apologize, but I didn\'t receive a response. Please try again.' 
            : '(Empty message)';
    }
    
    // Remove empty state if present
    const emptyState = messagesContainer.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    if (animate) {
        messageDiv.classList.add('message-enter');
    }
    
    const avatar = role === 'user' ? 'U' : 'AI';
    const avatarClass = role === 'user' ? 'user-avatar' : 'ai-avatar';
    
    messageDiv.innerHTML = `
        <div class="message-avatar ${avatarClass}">${avatar}</div>
        <div class="message-content">${escapeHtml(content)}</div>
    `;
    
    messagesContainer.appendChild(messageDiv);
    
    // Scroll to bottom
    setTimeout(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }, 100);
    
    // Remove animation class after animation
    if (animate) {
        setTimeout(() => {
            messageDiv.classList.remove('message-enter');
        }, 300);
    }
}

function createNewChat() {
    // Clear current chat
    currentChatId = null;
    
    // Clear messages display
    const messagesContainer = document.getElementById('messagesContainer');
    if (messagesContainer) {
        messagesContainer.innerHTML = '<div class="empty-state">Start a new conversation or select a chat from the sidebar</div>';
    }
    
    // Remove active state from all chat items
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });
    
    // Show empty state
    const emptyState = document.querySelector('.empty-state');
    if (emptyState) {
        emptyState.style.display = 'block';
    }
    
    // Focus on message input
    const messageInput = document.getElementById('messageInput');
    if (messageInput) {
        messageInput.focus();
    }
}

async function sendMessage() {
    const messageInput = document.getElementById('messageInput');
    if (!messageInput || !messageInput.value.trim()) return;
    
    // CRITICAL: Ensure chat screen is visible before sending
    const chatScreen = document.getElementById('chatScreen');
    if (chatScreen) {
        chatScreen.style.display = 'flex';
    }
    
    const message = messageInput.value.trim();
    messageInput.value = '';
    messageInput.style.height = 'auto';
    
    // Update activity timer
    resetActivityTimer();
    
    // Add user message
    addMessage('user', message);
    
    // Show "thinking" indicator
    const thinkingId = 'thinking-' + Date.now();
    addMessage('assistant', '...', false);
    const thinkingMsg = document.querySelector('.message.assistant:last-child');
    if (thinkingMsg) {
        thinkingMsg.id = thinkingId;
        thinkingMsg.querySelector('.message-content').innerHTML = '<div class="loading" style="margin: 0 auto;"></div><span style="margin-left: 8px; color: #666;">Thinking...</span>';
    }
    
    // Disable send button
    const sendBtn = document.getElementById('sendBtn');
    if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.innerHTML = '<div class="loading" style="width: 16px; height: 16px; margin: 0 auto;"></div>';
    }
    
    try {
        const response = await secureFetch(`${API_BASE_URL}/chat/message/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                content: message,
                chat_id: currentChatId || null
            })
        });

        if (response.ok && response.body) {
            await handleStreamedResponse(response, thinkingId);
        } else {
            // Remove thinking indicator
            const thinkingEl = document.getElementById(thinkingId);
            if (thinkingEl) {
                thinkingEl.remove();
            }
            const errorData = await response.json().catch(() => ({ detail: 'Failed to send message' }));
            addMessage('assistant', `Error: ${errorData.detail || 'Failed to send message'}`);
        }
    } catch (error) {
        // Remove thinking indicator
        const thinkingEl = document.getElementById(thinkingId);
        if (thinkingEl) {
            thinkingEl.remove();
        }
        console.error('Error sending message:', error);
        addMessage('assistant', 'Error: Failed to send message. Please try again.');
    } finally {
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
        }
    }
}

// Reads the "data: {json}\n\n" stream from /api/chat/message/stream and fills
// in the assistant bubble progressively as text arrives.
async function handleStreamedResponse(response, thinkingId) {
    const chatScreenEl = document.getElementById('chatScreen');
    if (chatScreenEl) {
        chatScreenEl.style.display = 'flex';
    }

    const messagesContainer = document.getElementById('messagesContainer');
    if (messagesContainer) {
        const emptyState = messagesContainer.querySelector('.empty-state');
        if (emptyState) emptyState.remove();
    }

    // Swap the "Thinking..." bubble for an empty assistant bubble we fill in live
    const thinkingEl = document.getElementById(thinkingId);
    if (thinkingEl) {
        thinkingEl.remove();
    }
    addMessage('assistant', '\u200B', false); // zero-width space placeholder while first tokens arrive (survives the empty-content check, unlike a plain space)
    const assistantBubble = messagesContainer ? messagesContainer.querySelector('.message.assistant:last-child') : null;
    const assistantContentEl = assistantBubble ? assistantBubble.querySelector('.message-content') : null;

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let accumulated = '';
    let gotAnyText = false;

    const applyText = (text) => {
        if (!assistantContentEl) return;
        assistantContentEl.textContent = text;
        if (messagesContainer) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    };

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let boundary;
        while ((boundary = buffer.indexOf('\n\n')) !== -1) {
            const rawEvent = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            if (!rawEvent.startsWith('data: ')) continue;

            let evt;
            try {
                evt = JSON.parse(rawEvent.slice(6));
            } catch (e) {
                continue;
            }

            if (evt.type === 'chunk') {
                accumulated += evt.text;
                gotAnyText = true;
                applyText(accumulated);
            } else if (evt.type === 'done') {
                accumulated = evt.response || accumulated;
                gotAnyText = true;
                applyText(accumulated);
                if (evt.chat_id && !currentChatId) {
                    currentChatId = evt.chat_id;
                    setTimeout(() => {
                        loadChats().catch(err => console.error('Error loading chats:', err));
                    }, 500);
                }
            } else if (evt.type === 'error') {
                applyText(`Error: ${evt.detail || 'Something went wrong. Please try again.'}`);
                gotAnyText = true;
            }
        }
    }

    if (!gotAnyText) {
        applyText("I apologize, but I didn't receive a response. Please try again.");
    }

    if (chatScreenEl) {
        chatScreenEl.style.display = 'flex';
    }
}

async function deleteChat(chatId, event) {
    if (event) {
        event.stopPropagation();
    }
    
    if (!confirm('Are you sure you want to delete this chat?')) {
        return;
    }
    
    try {
        const response = await secureFetch(`${API_BASE_URL}/chats/${chatId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            // If deleted chat was current, clear it
            if (currentChatId == chatId) {
                currentChatId = null;
                const messagesContainer = document.getElementById('messagesContainer');
                if (messagesContainer) {
                    messagesContainer.innerHTML = '<div class="empty-state">Start a new conversation or select a chat from the sidebar</div>';
                }
            }
            
            // Reload chat list
            loadChats();
        } else {
            alert('Failed to delete chat');
        }
    } catch (error) {
        console.error('Error deleting chat:', error);
        alert('Error deleting chat');
    }
}

// ============================================================================
// Document Management
// ============================================================================
async function loadDocuments() {
    if (!authToken) {
        console.warn('[loadDocuments] No auth token, skipping');
        return;
    }
    
    console.log('[loadDocuments] Starting document load...');
    console.log('[loadDocuments] Current user:', currentUser?.username, 'can_upload:', userCanUpload);
    
    try {
        const response = await secureFetch(`${API_BASE_URL}/documents`);
        console.log('[loadDocuments] API response status:', response.status);
        console.log('[loadDocuments] API response headers:', response.headers);
        
        if (response.ok) {
            const documents = await response.json();
            console.log('[loadDocuments] SUCCESS - Loaded', documents.length, 'documents');
            console.log('[loadDocuments] Documents array:', documents);
            
            if (documents && Array.isArray(documents)) {
                if (documents.length === 0) {
                    console.log('[loadDocuments] No documents returned (empty array)');
                } else {
                    console.log('[loadDocuments] Rendering', documents.length, 'documents');
                    documents.forEach((doc, idx) => {
                        console.log(`[loadDocuments]   Doc ${idx + 1}: ${doc.filename} (id: ${doc.id})`);
                    });
                }
                renderDocuments(documents);
                loadDocStats();
            } else {
                console.error('[loadDocuments] ERROR - Invalid response format:', documents);
                const docsList = document.getElementById('documentsList');
                if (docsList) {
                    docsList.innerHTML = '<div style="text-align: center; padding: 40px; color: #d32f2f;">Error: Invalid response format</div>';
                }
            }
        } else {
            const errorData = await response.json().catch(() => ({ detail: 'Failed to load documents' }));
            console.error('[loadDocuments] ERROR - Status:', response.status, 'Error:', errorData);
            const docsList = document.getElementById('documentsList');
            if (docsList) {
                docsList.innerHTML = `<div style="text-align: center; padding: 40px; color: #d32f2f;">Error: ${errorData.detail || 'Failed to load documents'} (Status: ${response.status})</div>`;
            }
        }
    } catch (error) {
        console.error('[loadDocuments] EXCEPTION:', error);
        const docsList = document.getElementById('documentsList');
        if (docsList) {
            docsList.innerHTML = `<div style="text-align: center; padding: 40px; color: #d32f2f;">Error loading documents: ${error.message}</div>`;
        }
    }
}

function renderDocuments(documents) {
    const docsList = document.getElementById('documentsList');
    if (!docsList) return;
    
    docsList.innerHTML = '';
    
    if (documents.length === 0) {
        docsList.innerHTML = '<div class="no-documents">No documents uploaded yet.</div>';
        return;
    }
    
    // Sort documents by upload date (newest first)
    const sortedDocs = [...documents].sort((a, b) => {
        const dateA = new Date(a.uploaded_at || 0);
        const dateB = new Date(b.uploaded_at || 0);
        return dateB - dateA;
    });
    
    sortedDocs.forEach(doc => {
        const docItem = document.createElement('div');
        docItem.className = 'document-item';
        
        // Show title if available, otherwise filename
        const displayName = doc.title || doc.filename;
        // Derive a 3-state status: indexed / failed / processing
        const status = doc.status || (doc.processed ? 'indexed' : 'processing');
        let statusIcon = '⏳', statusText = 'Processing', statusClass = 'processing';
        if (status === 'indexed' || doc.processed) {
            statusIcon = '✓'; statusText = 'Indexed'; statusClass = 'processed';
        } else if (status === 'failed') {
            statusIcon = '✕'; statusText = 'Failed'; statusClass = 'failed';
        }

        const errorLine = (status === 'failed' && doc.error_message)
            ? `<div class="document-error" title="${escapeHtml(doc.error_message)}">${escapeHtml(doc.error_message)}</div>`
            : '';
        const retryBtn = (status === 'failed')
            ? `<button class="retry-doc-btn" onclick="reindexDocument(${doc.id})" title="Retry indexing">↻ Retry</button>`
            : '';

        docItem.innerHTML = `
            <div class="document-info">
                <div class="document-header">
                    <span class="document-name">${escapeHtml(displayName)}</span>
                    <span class="document-status ${statusClass}">
                        ${statusIcon} ${statusText}
                    </span>
                </div>
                <div class="document-meta">
                    <span class="meta-item">${formatFileSize(doc.file_size)}</span>
                    <span class="meta-separator">•</span>
                    <span class="meta-item">${doc.chunk_count || 0} chunks</span>
                </div>
                ${errorLine}
            </div>
            <div class="document-actions">
                ${retryBtn}
                <button class="delete-doc-btn" onclick="deleteDocument(${doc.id})" title="Delete document">
                    🗑️
                </button>
            </div>
        `;
        docsList.appendChild(docItem);
    });

    // Stop polling once nothing is processing anymore
    const anyProcessing = sortedDocs.some(d => (d.status || (d.processed ? 'indexed' : 'processing')) === 'processing');
    if (!anyProcessing && docPollTimer) {
        clearTimeout(docPollTimer);
        docPollTimer = null;
    }
}

async function reindexDocument(docId) {
    try {
        const response = await secureFetch(`${API_BASE_URL}/documents/${docId}/reindex`, {
            method: 'POST'
        });
        if (response.ok) {
            showNotification('Re-indexing started...', 'success');
            loadDocuments();
            pollDocumentsWhileProcessing();
        } else {
            const err = await response.json().catch(() => ({ detail: 'Retry failed' }));
            showNotification(err.detail || 'Retry failed', 'error');
        }
    } catch (e) {
        console.error('Error re-indexing document:', e);
        showNotification('Error starting re-index', 'error');
    }
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

async function deleteDocument(docId) {
    if (!confirm('Are you sure you want to delete this document?')) {
        return;
    }
    
    try {
        const response = await secureFetch(`${API_BASE_URL}/documents/${docId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadDocuments();
        } else {
            alert('Failed to delete document');
        }
    } catch (error) {
        console.error('Error deleting document:', error);
        alert('Error deleting document');
    }
}

async function loadDocStats() {
    try {
        const response = await secureFetch(`${API_BASE_URL}/documents/stats`);
        if (response.ok) {
            const stats = await response.json();
            const statsEl = document.getElementById('docStats');
            if (statsEl) {
                // Show both SQL and vector DB counts if available
                let statsText = `${stats.total_documents || 0} documents`;
                
                if (stats.total_chunks_in_vector_db !== undefined && stats.total_chunks_in_vector_db !== null) {
                    // Show actual vector DB count
                    statsText += ` • ${stats.total_chunks_in_vector_db} chunks in vector DB`;
                    
                    // Show warning if mismatch
                    if (stats.vector_db_synced === false) {
                        statsText += ` ⚠️ (SQL shows ${stats.total_chunks || 0} chunks - mismatch!)`;
                        statsEl.style.color = '#d32f2f';
                        statsEl.style.fontWeight = '600';
                    } else {
                        statsEl.style.color = '';
                        statsEl.style.fontWeight = '';
                    }
                } else {
                    // Fallback to SQL count
                    statsText += ` • ${stats.total_chunks || 0} chunks indexed`;
                    statsEl.style.color = '';
                    statsEl.style.fontWeight = '';
                }
                
                statsEl.textContent = statsText;
            }
        }
    } catch (error) {
        console.error('Error loading doc stats:', error);
    }
}

// ============================================================================
// File Upload
// ============================================================================
function handleFileUpload() {
    const fileInput = document.getElementById('fileInput');
    if (fileInput) {
        fileInput.click();
    }
}

// Function to process uploaded files (used by both click and drag-drop)
async function processFiles(files) {
    if (!files || files.length === 0) return;
    
    // Process each file
    for (const file of files) {
        // Check file type
        const fileExt = '.' + file.name.split('.').pop().toLowerCase();
        if (!allowedExtensions.includes(fileExt)) {
            showNotification(
                `Invalid file type: ${file.name}. Allowed types: ${formatAllowedTypesHint(allowedExtensions)}.`,
                'error'
            );
            continue;
        }
        
        // Check file size (limit comes from server config)
        if (file.size > maxUploadMb * 1024 * 1024) {
            showNotification(`File too large: ${file.name}. Maximum size is ${maxUploadMb}MB.`, 'error');
            continue;
        }
        
        // Show progress container
        const progressContainer = document.getElementById('uploadProgressContainer');
        const progressDiv = document.getElementById('uploadProgress');
        
        if (progressContainer && progressDiv) {
            progressContainer.style.display = 'block';
            progressDiv.innerHTML = `
                <div style="background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <div style="font-weight: 600; color: var(--e-text);">Uploading: ${escapeHtml(file.name)}</div>
                        <div id="uploadPercent_${file.name.replace(/[^a-zA-Z0-9]/g, '_')}" style="font-weight: 600; color: var(--e-red);">0%</div>
                    </div>
                    <div style="background: #f0f0f0; border-radius: 4px; height: 8px; overflow: hidden; margin-bottom: 8px;">
                        <div id="uploadBar_${file.name.replace(/[^a-zA-Z0-9]/g, '_')}" style="background: var(--e-red); height: 100%; width: 0%; transition: width 0.3s ease;"></div>
                    </div>
                    <div id="uploadStatus_${file.name.replace(/[^a-zA-Z0-9]/g, '_')}" style="font-size: 13px; color: var(--e-text-light);">Preparing upload...</div>
                </div>
            `;
        }
        
        const formData = new FormData();
        formData.append('file', file);
        
        const fileId = file.name.replace(/[^a-zA-Z0-9]/g, '_');
        
        try {
            // Update status
            const statusEl = document.getElementById(`uploadStatus_${fileId}`);
            if (statusEl) statusEl.textContent = 'Uploading file...';
            
            // Simulate progress (since we can't track actual upload progress with fetch)
            let progress = 0;
            const progressInterval = setInterval(() => {
                progress += Math.random() * 15;
                if (progress > 90) progress = 90;
                const barEl = document.getElementById(`uploadBar_${fileId}`);
                const percentEl = document.getElementById(`uploadPercent_${fileId}`);
                if (barEl) barEl.style.width = progress + '%';
                if (percentEl) percentEl.textContent = Math.round(progress) + '%';
            }, 200);
            
            const response = await secureFetch(`${API_BASE_URL}/documents/upload`, {
                method: 'POST',
                body: formData
            });
            
            clearInterval(progressInterval);
            
            // Complete progress bar
            const barEl = document.getElementById(`uploadBar_${fileId}`);
            const percentEl = document.getElementById(`uploadPercent_${fileId}`);
            if (barEl) barEl.style.width = '100%';
            if (percentEl) percentEl.textContent = '100%';
            
            if (response.ok) {
                const data = await response.json();
                const statusEl = document.getElementById(`uploadStatus_${fileId}`);
                if (statusEl) {
                    statusEl.textContent = 'Uploaded. Indexing in the background — it will show as "Indexed" when ready.';
                    statusEl.style.color = 'var(--e-red)';
                    statusEl.style.fontWeight = '600';
                }

                // Hide progress after a few seconds
                setTimeout(() => {
                    if (progressContainer) {
                        progressContainer.style.display = 'none';
                    }
                }, 4000);

                showNotification(`"${file.name}" uploaded. Indexing in the background...`, 'success');

                // Reload + poll so it flips from Processing to Indexed automatically
                const documentsScreen = document.getElementById('documentsScreen');
                if (documentsScreen && documentsScreen.style.display !== 'none') {
                    loadDocuments();
                    pollDocumentsWhileProcessing();
                }
            } else {
                const errorData = await response.json().catch(() => ({ detail: 'Upload failed' }));
                const statusEl = document.getElementById(`uploadStatus_${fileId}`);
                if (statusEl) {
                    statusEl.textContent = `Error: ${errorData.detail || 'Upload failed'}`;
                    statusEl.style.color = '#d32f2f';
                }
                showNotification(errorData.detail || 'Failed to upload document', 'error');
            }
        } catch (error) {
            console.error('Error uploading file:', error);
            const statusEl = document.getElementById(`uploadStatus_${fileId}`);
            if (statusEl) {
                statusEl.textContent = 'Error: Upload failed. Please try again.';
                statusEl.style.color = '#d32f2f';
            }
            showNotification('Error uploading file. Please try again.', 'error');
        }
    }
}

// File input change handler (for click upload)
document.getElementById('fileInput')?.addEventListener('change', async (e) => {
    if (!userCanUpload) {
        showNotification('You do not have permission to upload documents.', 'error');
        e.target.value = '';
        return;
    }
    
    const files = Array.from(e.target.files);
    e.target.value = ''; // Reset file input
    
    await processFiles(files);
});

// ============================================================================
// Admin Functions
// ============================================================================
async function loadUsers() {
    if (!userIsAdmin) return;
    
    try {
        const response = await secureFetch(`${API_BASE_URL}/admin/users`);
        if (response.ok) {
            const users = await response.json();
            renderUsers(users);
        }
    } catch (error) {
        console.error('Error loading users:', error);
    }
}

function renderUsers(users) {
    const usersList = document.getElementById('usersList');
    if (!usersList) return;
    
    usersList.innerHTML = '';
    
    users.forEach(user => {
        const userItem = document.createElement('div');
        userItem.className = 'user-item';
        const isSelf = currentUser && currentUser.id === user.id;
        userItem.innerHTML = `
            <div class="user-info">
                <div class="user-name">${escapeHtml(user.full_name || user.username)}</div>
                <div class="user-meta">${escapeHtml(user.username)} ${user.is_admin ? '(Admin)' : ''}</div>
            </div>
            <div class="user-actions" style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
                <label class="toggle-switch">
                    <input type="checkbox" ${user.can_upload ? 'checked' : ''} 
                           onchange="updateUserPermission(${user.id}, this.checked)">
                    <span class="toggle-slider"></span>
                </label>
                <span class="toggle-label">Can Upload</span>
                <button class="btn-small" onclick="adminResetPassword(${user.id}, '${escapeHtml(user.username)}')">Reset Password</button>
                <button class="btn-small danger" onclick="adminDeleteUser(${user.id}, '${escapeHtml(user.username)}')" ${isSelf ? 'disabled title="You cannot delete your own account"' : ''}>Delete</button>
            </div>
        `;
        usersList.appendChild(userItem);
    });
}

async function adminResetPassword(userId, username) {
    const newPassword = prompt(`Enter a new password for "${username}":`);
    if (newPassword === null) return; // cancelled
    if (!newPassword.trim()) {
        showNotification('Password cannot be empty.', 'error');
        return;
    }
    try {
        const response = await secureFetch(`${API_BASE_URL}/admin/users/${userId}/reset-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_password: newPassword })
        });
        if (response.ok) {
            showNotification(`Password reset for "${username}".`, 'success');
        } else {
            const data = await response.json().catch(() => ({ detail: 'Failed to reset password' }));
            showNotification(data.detail || 'Failed to reset password.', 'error');
        }
    } catch (error) {
        console.error('Error resetting password:', error);
        showNotification('Error resetting password.', 'error');
    }
}
window.adminResetPassword = adminResetPassword;

async function adminDeleteUser(userId, username) {
    if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;
    try {
        const response = await secureFetch(`${API_BASE_URL}/admin/users/${userId}`, {
            method: 'DELETE'
        });
        if (response.ok) {
            showNotification(`User "${username}" deleted.`, 'success');
            loadUsers();
        } else {
            const data = await response.json().catch(() => ({ detail: 'Failed to delete user' }));
            showNotification(data.detail || 'Failed to delete user.', 'error');
        }
    } catch (error) {
        console.error('Error deleting user:', error);
        showNotification('Error deleting user.', 'error');
    }
}
window.adminDeleteUser = adminDeleteUser;

async function updateUserPermission(userId, canUpload) {
    try {
        const response = await secureFetch(`${API_BASE_URL}/admin/users/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ can_upload: canUpload })
        });
        
        if (!response.ok) {
            alert('Failed to update user permission');
        }
    } catch (error) {
        console.error('Error updating user permission:', error);
        alert('Error updating user permission');
    }
}


// ============================================================================
// Utility Functions
// ============================================================================
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showNotification(message, type = 'info') {
    // Simple notification - could be enhanced with a toast library
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        background: ${type === 'success' ? '#4CAF50' : type === 'error' ? '#f44336' : '#2196F3'};
        color: white;
        border-radius: 4px;
        z-index: 10000;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// Wrapper for fetch that handles 401 (expired token) globally
async function secureFetch(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            ...options.headers,
            'Authorization': `Bearer ${authToken}`
        }
    });
    
    // If token expired, handle it globally
    if (response.status === 401) {
        handleAuthFailure('Your session has expired. Please login again.');
        throw new Error('Unauthorized - session expired');
    }
    
    return response;
}

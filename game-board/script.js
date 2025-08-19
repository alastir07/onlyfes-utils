// Base Grid class with common functionality
class BaseGrid {
    constructor() {
        this.gameBoard = document.getElementById('gameBoard');
        this.tileDetails = document.getElementById('tileDetails');
        this.tileContent = document.getElementById('tileContent');
        this.editControls = document.getElementById('editControls');
        this.editModeToggle = document.getElementById('editModeToggle');
        this.gridTypeToggle = document.getElementById('gridTypeToggle');
        this.tiles = new Map();
        this.contextMenu = null;
        
        // Grid dimensions
        this.gridRadius = 10;
        
        // Viewport position and zoom
        this.viewportX = window.innerWidth / 2;
        this.viewportY = window.innerHeight / 2;
        this.zoom = 1;
        this.isDragging = false;
        this.dragStart = { x: 0, y: 0 };
        
        // Edit mode state
        this.isEditMode = false;
        
        // Grid type
        this.gridType = 'hex'; // 'hex' or 'square'
    }

    setupCommonEventListeners() {
        // Add event listeners
        this.gameBoard.addEventListener('click', this.handleBoardClick.bind(this));
        this.setupDragHandlers();
        this.setupEditModeHandlers();
        this.setupZoomHandlers();
        document.addEventListener('click', this.hideContextMenu.bind(this));
        
        // Add save/load event listeners
        document.getElementById('saveBoard').addEventListener('click', () => this.saveBoard());
        document.getElementById('loadBoard').addEventListener('click', () => {
            document.getElementById('boardFile').click();
        });
        document.getElementById('boardFile').addEventListener('change', (e) => this.loadBoard(e));
        document.getElementById('shareBoard').addEventListener('click', () => this.shareBoard());

        // Add sidebar toggle listener
        document.getElementById('toggleSidebar').addEventListener('click', () => this.toggleSidebar());

        // Add grid type toggle listener
        this.gridTypeToggle.addEventListener('click', () => this.toggleGridType());
    }

    toggleGridType() {
        // Check if there are any filled tiles
        const filledTiles = Array.from(this.tiles.values()).filter(tile => 
            tile.element.classList.contains('filled')
        );
        
        if (filledTiles.length > 0) {
            // Show warning dialog
            const newGridType = this.gridType === 'hex' ? 'square' : 'hex';
            const newGridName = newGridType === 'hex' ? 'hexagonal' : 'square';
            const currentGridName = this.gridType === 'hex' ? 'hexagonal' : 'square';
            
            const confirmed = confirm(
                `Switching from ${currentGridName} to ${newGridName} grid will clear all current tiles and reset the board.\n\n` +
                `This action cannot be undone. Do you want to continue?`
            );
            
            if (!confirmed) {
                return; // User cancelled, don't switch
            }
        }
        
        // Switch grid type
        this.gridType = this.gridType === 'hex' ? 'square' : 'hex';
        
        // Update button text
        this.gridTypeToggle.textContent = this.gridType === 'hex' ? '⬡ Hexes' : '⬛ Squares';
        
        // Update grid size calculations based on type
        if (this.gridType === 'square') {
            this.squareSize = 80;
            this.squareSpacing = 5;
            this.xStep = this.squareSize + this.squareSpacing;
            this.yStep = this.squareSize + this.squareSpacing;
        } else {
            this.hexSize = 50;
            this.hexWidth = this.hexSize * Math.sqrt(3);
            this.hexHeight = this.hexSize * 2;
            this.hexSpacing = 5;
            this.xStep = this.hexWidth + this.hexSpacing;
            this.yStep = (this.hexHeight * 3/4) + (this.hexSpacing * Math.cos(Math.PI/6));
        }
        
        // Clear current grid and reset to blank state
        this.gameBoard.innerHTML = '';
        this.tiles.clear();
        
        // Hide tile details panel
        this.tileDetails.classList.remove('active');
        
        // Reinitialize with new grid type (blank)
        this.initializeGrid();
        
        // Update positions
        this.updateTilePositions();
    }

    getBoardData() {
        return {
            viewportX: this.viewportX,
            viewportY: this.viewportY,
            zoom: this.zoom,
            isEditMode: this.isEditMode,
            gridType: this.gridType,
            tiles: Array.from(this.tiles.entries())
                .filter(([_, tile]) => tile.element.classList.contains('filled'))
                .map(([key, tile]) => ({
                    key,
                    q: tile.q,
                    r: tile.r,
                    backgroundImage: tile.backgroundImage,
                    details: tile.details
                }))
        };
    }
}

class HexGrid extends BaseGrid {
    constructor() {
        super();
        this.gridType = 'hex';

        // Size calculations for perfect hexagon tiling
        this.hexSize = 50; // Distance from center to corner
        this.hexWidth = this.hexSize * Math.sqrt(3); // Width of hexagon
        this.hexHeight = this.hexSize * 2; // Height of hexagon
        this.hexSpacing = 5; // Gap between adjacent tiles
        
        // Size calculations for square grid
        this.squareSize = 80; // Size of each square
        this.squareSpacing = 5; // Gap between squares
        
        // Calculate offsets based on hexagon geometry (default)
        this.xStep = this.hexWidth + this.hexSpacing;
        this.yStep = (this.hexHeight * 3/4) + (this.hexSpacing * Math.cos(Math.PI/6));
        
        // Initialize the grid
        this.initializeGrid();
        
        // Setup event listeners
        this.setupCommonEventListeners();

        // Create edge arrows
        this.createEdgeArrows();
    }

    initializeGrid() {
        // Clear existing tiles
        this.gameBoard.innerHTML = '';
        this.tiles.clear();

        if (this.gridType === 'square') {
            // Create a square grid
            for (let q = -this.gridRadius; q <= this.gridRadius; q++) {
                for (let r = -this.gridRadius; r <= this.gridRadius; r++) {
                    this.createEmptySquare(q, r);
                }
            }
        } else {
            // Create a hexagonal grid with offset rows
            for (let q = -this.gridRadius; q <= this.gridRadius; q++) {
                for (let r = -this.gridRadius; r <= this.gridRadius; r++) {
                    // Offset alternate rows
                    const offsetQ = q + (r % 2) * 0.5;
                    // Check if this hex is within the circular radius
                    if (Math.abs(offsetQ) + Math.abs(r) <= this.gridRadius * 2) {
                        this.createEmptyHex(offsetQ, r);
                    }
                }
            }
        }

        // Initialize with center tile filled
        this.toggleTile(0, 0);
    }

    createEmptyHex(q, r) {
        const key = `${q},${r}`;
        const { x, y } = this.gridToPixel(q, r);
        
        const hex = document.createElement('div');
        hex.className = 'hex';
        hex.style.left = `${x}px`;
        hex.style.top = `${y}px`;

        const content = document.createElement('div');
        content.className = 'hex-content';
        content.style.backgroundImage = 'url("https://via.placeholder.com/100x115")';
        hex.appendChild(content);

        const tileData = {
            element: hex,
            q,
            r,
            backgroundImage: content.style.backgroundImage,
            details: {
                name: `Tile ${key}`,
                description: 'Click to edit details'
            }
        };
        
        // Set initial border color
        hex.style.borderColor = tileData.details.borderColor;
        if (content) {
            content.style.borderColor = tileData.details.borderColor;
        }

        hex.addEventListener('click', (e) => {
            // Only toggle if we're in edit mode and this wasn't a drag
            if (this.isEditMode && !this.gameBoard.classList.contains('dragging')) {
                this.toggleTile(q, r);
            }
        });

        hex.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            if (this.isEditMode && hex.classList.contains('filled')) {
                this.showContextMenu(e, key);
            }
        });

        this.tiles.set(key, tileData);
        this.gameBoard.appendChild(hex);
    }

    createEmptySquare(q, r) {
        const key = `${q},${r}`;
        const { x, y } = this.gridToPixel(q, r);
        
        const square = document.createElement('div');
        square.className = 'square';
        square.style.left = `${x}px`;
        square.style.top = `${y}px`;

        const content = document.createElement('div');
        content.className = 'square-content';
        content.style.backgroundImage = 'url("https://via.placeholder.com/80x80")';
        square.appendChild(content);

        const tileData = {
            element: square,
            q,
            r,
            backgroundImage: content.style.backgroundImage,
            details: {
                name: `Tile ${key}`,
                description: 'Click to edit details'
            }
        };

        square.addEventListener('click', (e) => {
            // Only toggle if we're in edit mode and this wasn't a drag
            if (this.isEditMode && !this.gameBoard.classList.contains('dragging')) {
                this.toggleTile(q, r);
            }
        });

        square.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            if (this.isEditMode && square.classList.contains('filled')) {
                this.showContextMenu(e, key);
            }
        });

        this.tiles.set(key, tileData);
        this.gameBoard.appendChild(square);
    }

    showContextMenu(e, key) {
        this.hideContextMenu();
        
        const menu = document.createElement('div');
        menu.className = 'context-menu';
        menu.style.left = `${e.pageX}px`;
        menu.style.top = `${e.pageY}px`;

        const items = [
            {
                text: 'Edit Details',
                onClick: () => this.showTileDetails(key)
            }
        ];

        items.forEach(item => {
            const menuItem = document.createElement('div');
            menuItem.className = 'context-menu-item' + (item.className ? ` ${item.className}` : '');
            menuItem.textContent = item.text;
            menuItem.onclick = () => {
                item.onClick();
                this.hideContextMenu();
            };
            menu.appendChild(menuItem);
        });

        document.body.appendChild(menu);
        this.contextMenu = menu;

        // Adjust menu position if it would go off screen
        const menuRect = menu.getBoundingClientRect();
        if (menuRect.right > window.innerWidth) {
            menu.style.left = `${window.innerWidth - menuRect.width}px`;
        }
        if (menuRect.bottom > window.innerHeight) {
            menu.style.top = `${window.innerHeight - menuRect.height}px`;
        }
    }

    hideContextMenu() {
        if (this.contextMenu) {
            this.contextMenu.remove();
            this.contextMenu = null;
        }
    }

    toggleTile(q, r) {
        const key = `${q},${r}`;
        const tile = this.tiles.get(key);
        if (!tile) return;

        tile.element.classList.toggle('filled');
    }

    // Update save/load to handle filled state
    saveBoard() {
        const boardData = this.getBoardData();

        const blob = new Blob([JSON.stringify(boardData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${this.gridType}-board.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    loadBoard(event) {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const boardData = JSON.parse(e.target.result);
                
                // Detect grid type if not explicitly specified
                if (!boardData.gridType && boardData.tiles && boardData.tiles.length > 0) {
                    // Try to detect grid type based on coordinate patterns
                    boardData.gridType = this.detectGridType(boardData.tiles);
                }
                
                // Switch grid type if needed
                if (boardData.gridType && boardData.gridType !== this.gridType) {
                    const oldGridType = this.gridType;
                    this.gridType = boardData.gridType;
                    this.gridTypeToggle.textContent = this.gridType === 'hex' ? '⬡ Hexes' : '⬛ Squares';
                    
                    // Update grid size calculations based on detected type
                    if (this.gridType === 'square') {
                        this.squareSize = 80;
                        this.squareSpacing = 5;
                        this.xStep = this.squareSize + this.squareSpacing;
                        this.yStep = this.squareSize + this.squareSpacing;
                    } else {
                        this.hexSize = 50;
                        this.hexWidth = this.hexSize * Math.sqrt(3);
                        this.hexHeight = this.hexSize * 2;
                        this.hexSpacing = 5;
                        this.xStep = this.hexWidth + this.hexSpacing;
                        this.yStep = (this.hexHeight * 3/4) + (this.hexSpacing * Math.cos(Math.PI/6));
                    }
                    
                    // Show user-friendly notification
                    const gridTypeName = this.gridType === 'hex' ? 'hexagonal' : 'square';
                    const oldGridTypeName = oldGridType === 'hex' ? 'hexagonal' : 'square';
                    console.log(`Automatically switched from ${oldGridTypeName} to ${gridTypeName} grid based on loaded board data.`);
                }
                
                // Initialize empty grid first
                this.initializeGrid();
                
                this.viewportX = boardData.viewportX || window.innerWidth / 2;
                this.viewportY = boardData.viewportY || window.innerHeight / 2;
                this.zoom = boardData.zoom || 1;
                
                if (boardData.isEditMode !== undefined) {
                    this.isEditMode = boardData.isEditMode;
                    this.updateEditModeUI();
                }
                
                // Fill and update tiles
                boardData.tiles.forEach(tileData => {
                    const { q, r, backgroundImage, details } = tileData;
                    const key = `${q},${r}`;
                    const tile = this.tiles.get(key);
                    if (tile) {
                        tile.element.classList.add('filled');
                        tile.backgroundImage = backgroundImage;
                        tile.details = details;
                        const contentSelector = this.gridType === 'hex' ? '.hex-content' : '.square-content';
                        const content = tile.element.querySelector(contentSelector);
                        if (content) {
                            content.style.backgroundImage = backgroundImage;
                        }
                    }
                });

                this.updateTilePositions();
            } catch (error) {
                alert('Error loading board configuration: ' + error.message);
            }
        };
        reader.readAsText(file);
    }

    detectGridType(tiles) {
        // Analyze tile coordinates to determine if it's a hex or square grid
        // Hex grids typically have fractional q coordinates due to offset rows
        // Square grids have integer coordinates in a regular pattern
        
        const coordinates = tiles.map(tile => ({ q: tile.q, r: tile.r }));
        
        // Check for fractional coordinates (typical of hex grids with offset rows)
        const hasFractionalCoords = coordinates.some(coord => 
            coord.q % 1 !== 0 || coord.r % 1 !== 0
        );
        
        if (hasFractionalCoords) {
            return 'hex';
        }
        
        // Check coordinate distribution patterns
        // Square grids tend to have more regular, rectangular patterns
        // Hex grids tend to have more circular/hexagonal patterns
        
        if (coordinates.length >= 3) {
            // Look for typical hex offset patterns (like 0.5 offsets)
            const hasHexOffsets = coordinates.some(coord => 
                Math.abs(coord.q - Math.round(coord.q)) === 0.5
            );
            
            if (hasHexOffsets) {
                return 'hex';
            }
            
            // If all coordinates are integers, check for square-like patterns
            const allIntegers = coordinates.every(coord => 
                coord.q % 1 === 0 && coord.r % 1 === 0
            );
            
            if (allIntegers) {
                // Check if coordinates form more of a square pattern
                const qValues = coordinates.map(c => c.q);
                const rValues = coordinates.map(c => c.r);
                const qRange = Math.max(...qValues) - Math.min(...qValues);
                const rRange = Math.max(...rValues) - Math.min(...rValues);
                
                // If the ranges are similar, it's likely a square grid
                if (qRange > 0 && rRange > 0 && Math.abs(qRange - rRange) <= 2) {
                    return 'square';
                }
            }
        }
        
        // Default to hex if we can't determine
        return 'hex';
    }

    setupEditModeHandlers() {
        this.editModeToggle.addEventListener('click', () => {
            this.isEditMode = !this.isEditMode;
            this.updateEditModeUI();
        });
    }

    updateEditModeUI() {
        // Update button text and style
        this.editModeToggle.textContent = this.isEditMode ? '✏️ Edit Mode' : '🔒 View Mode';
        this.editModeToggle.classList.toggle('edit-mode', this.isEditMode);
        
        // Update other UI elements
        this.editControls.classList.toggle('active', this.isEditMode);
        this.gameBoard.classList.toggle('edit-mode', this.isEditMode);
        
        // Hide tile details when switching modes
        this.tileDetails.classList.remove('active');
        
        // Update all tiles and their add buttons
        this.tiles.forEach((tile, key) => {
            tile.element.classList.toggle('edit-mode', this.isEditMode);
        });
    }

    setupDragHandlers() {
        let isDragging = false;
        let dragStart = { x: 0, y: 0 };
        let dragStartTime = 0;
        const DRAG_THRESHOLD = 200; // milliseconds

        this.gameBoard.addEventListener('mousedown', (e) => {
            // Only start drag if it's a left click
            if (e.button !== 0) return;

            isDragging = false;
            dragStartTime = Date.now();
            dragStart = {
                x: e.clientX - this.viewportX,
                y: e.clientY - this.viewportY
            };

            const handleMouseMove = (e) => {
                const dx = e.clientX - (dragStart.x + this.viewportX);
                const dy = e.clientY - (dragStart.y + this.viewportY);
                const distance = Math.sqrt(dx * dx + dy * dy);

                if (distance > 5) { // 5px threshold for drag
                    isDragging = true;
                    this.gameBoard.classList.add('dragging');
                }

                if (isDragging) {
                    this.viewportX = e.clientX - dragStart.x;
                    this.viewportY = e.clientY - dragStart.y;
                    this.updateTilePositions();
                }
            };

            const handleMouseUp = (e) => {
                window.removeEventListener('mousemove', handleMouseMove);
                window.removeEventListener('mouseup', handleMouseUp);
                
                if (isDragging) {
                    e.preventDefault();
                    e.stopPropagation();
                }
                
                isDragging = false;
                this.gameBoard.classList.remove('dragging');
            };

            window.addEventListener('mousemove', handleMouseMove);
            window.addEventListener('mouseup', handleMouseUp);
        });

        // Prevent default drag behavior
        this.gameBoard.addEventListener('dragstart', (e) => e.preventDefault());
    }

    setupZoomHandlers() {
        // Add zoom buttons to controls
        const zoomControls = document.createElement('div');
        zoomControls.className = 'zoom-controls';
        zoomControls.innerHTML = `
            <button id="zoomIn">+</button>
            <button id="zoomOut">-</button>
        `;
        this.editControls.appendChild(zoomControls);

        // Add wheel zoom
        this.gameBoard.addEventListener('wheel', (e) => {
            e.preventDefault();
            const zoomFactor = 1.1;
            const delta = e.deltaY > 0 ? 1/zoomFactor : zoomFactor;
            this.setZoom(this.zoom * delta);
        });

        // Add button zoom
        document.getElementById('zoomIn').addEventListener('click', () => {
            this.setZoom(this.zoom * 1.1);
        });

        document.getElementById('zoomOut').addEventListener('click', () => {
            this.setZoom(this.zoom * 0.9);
        });
    }

    setZoom(newZoom) {
        // Clamp zoom between 0.5 and 2
        this.zoom = Math.max(0.5, Math.min(2, newZoom));
        
        if (this.gridType === 'square') {
            // Update square sizes while keeping spacing consistent
            const baseSize = 80;
            this.squareSize = baseSize * this.zoom;
            this.xStep = this.squareSize + this.squareSpacing;
            this.yStep = this.squareSize + this.squareSpacing;

            // Update CSS variables for square sizing
            this.gameBoard.style.setProperty('--square-size', `${this.squareSize}px`);
        } else {
            // Update hex sizes while keeping spacing consistent
            const baseSize = 50;
            this.hexSize = baseSize * this.zoom;
            this.hexWidth = this.hexSize * Math.sqrt(3);
            this.hexHeight = this.hexSize * 2;
            this.xStep = this.hexWidth + this.hexSpacing;
            this.yStep = (this.hexHeight * 3/4) + (this.hexSpacing * Math.cos(Math.PI/6));

            // Update CSS variables for hex sizing
            this.gameBoard.style.setProperty('--hex-size', `${this.hexSize}px`);
            this.gameBoard.style.setProperty('--hex-width', `${this.hexWidth}px`);
            this.gameBoard.style.setProperty('--hex-height', `${this.hexHeight}px`);
        }
        
        this.updateTilePositions();
    }

    // Convert grid coordinates to pixel coordinates
    gridToPixel(q, r) {
        if (this.gridType === 'square') {
            const x = q * this.xStep;
            const y = r * this.yStep;
            return { 
                x: x + this.viewportX, 
                y: y + this.viewportY 
            };
        } else {
            const x = q * this.xStep;
            const y = -r * this.yStep;
            return { 
                x: x + this.viewportX, 
                y: y + this.viewportY 
            };
        }
    }

    // Update all tile positions based on viewport
    updateTilePositions() {
        this.tiles.forEach((tile, key) => {
            const { x, y } = this.gridToPixel(tile.q, tile.r);
            tile.element.style.left = `${x}px`;
            tile.element.style.top = `${y}px`;
        });
    }

    // Show tile details in the side panel
    showTileDetails(key) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        let content = `
            <div class="tile-details-content">
                <div class="details-section">
                    ${this.isEditMode ? `
                        <div class="details-header">
                            <h3>Details</h3>
                            <div class="details-actions" id="detailsActions">
                                <button class="edit-link" onclick="hexGrid.startEditing('${key}')">Edit</button>
                                <button class="reset-link" onclick="hexGrid.resetTile('${key}')">Reset</button>
                            </div>
                        </div>
                    ` : ''}
                    ${this.isEditMode ? `
                        <div class="details-field">
                            <span class="details-label">Title:</span>
                            <div class="details-value" id="tileTitle">
                                ${tile.details.title || `Tile ${key}`}
                            </div>
                        </div>
                    ` : ''}
                    <div class="details-field">
                        ${this.isEditMode ? `<span class="details-label">Description:</span>` : ''}
                        <div class="details-value" id="tileDescription">
                            ${tile.details.description}
                        </div>
                    </div>
                </div>
                ${this.isEditMode ? `
                    <div class="item-search-section">
                        <h3>OSRS Item Search</h3>
                        <div class="search-container">
                            <input type="text" id="itemSearch" placeholder="Search for an OSRS item...">
                            <button onclick="hexGrid.searchOSRSItem('${key}')">Search</button>
                        </div>
                        <div id="searchResults" class="search-results"></div>
                    </div>
                ` : ''}
                <div class="image-section">
                    ${this.isEditMode ? `<h3>Image</h3>` : ''}
                    <div class="image-preview">
                        <img src="${tile.backgroundImage.replace(/url\(['"](.+)['"]\)/, '$1')}" alt="Tile preview">
                    </div>
                    ${this.isEditMode ? `<button onclick="hexGrid.changeTileImage('${key}')">Change Image</button>` : ''}
                </div>
            </div>
        `;

        this.tileContent.innerHTML = content;
        this.tileDetails.classList.add('active');

        // Update the sidebar header with the tile title in view mode
        if (!this.isEditMode) {
            const headerTitle = this.tileDetails.querySelector('.tile-details-header h2');
            if (headerTitle) {
                headerTitle.textContent = tile.details.title || `Tile ${key}`;
            }
        }
    }

    async searchOSRSItem(key) {
        const searchInput = document.getElementById('itemSearch');
        const searchTerm = searchInput.value.trim();
        if (!searchTerm) return;

        const searchResults = document.getElementById('searchResults');
        searchResults.innerHTML = '<div class="loading">Searching...</div>';

        try {
            // Use the OSRS Wiki API to search for items
            const response = await fetch(`https://oldschool.runescape.wiki/api.php?action=query&list=search&srsearch=${encodeURIComponent(searchTerm)}&format=json&origin=*`);
            const data = await response.json();
            
            if (data.query && data.query.search) {
                const results = data.query.search;
                if (results.length > 0) {
                    // Get the first result and fetch its image
                    const pageId = results[0].pageid;
                    const imageResponse = await fetch(`https://oldschool.runescape.wiki/api.php?action=query&prop=pageimages&piprop=original&pageids=${pageId}&format=json&origin=*`);
                    const imageData = await imageResponse.json();
                    
                    const page = imageData.query.pages[pageId];
                    if (page.original) {
                        const imageUrl = page.original.source;
                        const wikiUrl = `https://oldschool.runescape.wiki/w/${encodeURIComponent(results[0].title.replace(/ /g, '_'))}`;
                        
                        // Update the tile with the item image and wiki link
                        const tile = this.tiles.get(key);
                        if (tile) {
                            tile.backgroundImage = `url("${imageUrl}")`;
                            const contentSelector = this.gridType === 'hex' ? '.hex-content' : '.square-content';
                            const content = tile.element.querySelector(contentSelector);
                            if (content) {
                                content.style.backgroundImage = tile.backgroundImage;
                            }
                            tile.details.description = `<a href="${wikiUrl}" target="_blank">${results[0].title}</a>`;
                            this.showTileDetails(key);
                        }
                    }
                } else {
                    searchResults.innerHTML = '<div class="no-results">No items found</div>';
                }
            }
        } catch (error) {
            console.error('Error searching for OSRS item:', error);
            searchResults.innerHTML = '<div class="error">Error searching for item</div>';
        }
    }

    updateBorderColor(key, color) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        tile.details.borderColor = color;
        tile.element.style.setProperty('--border-color', color);
        this.showTileDetails(key);
    }

    resetTile(key) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        // Reset to default values
        tile.backgroundImage = 'url("https://via.placeholder.com/100x115")';
        tile.element.querySelector('.hex-content').style.backgroundImage = tile.backgroundImage;
        tile.details.title = `Tile ${key}`;
        tile.details.description = 'Click to edit details';

        // Refresh the tile details view
        this.showTileDetails(key);
    }

    // Handle clicks on the game board
    handleBoardClick(e) {
        if (e.target === this.gameBoard) {
            this.tileDetails.classList.remove('active');
        } else {
            // Check for both hex and square tiles
            const tile = e.target.closest('.hex') || e.target.closest('.square');
            if (tile) {
                const key = Array.from(this.tiles.keys()).find(k => this.tiles.get(k).element === tile);
                if (key) {
                    this.showTileDetails(key);
                }
            }
        }
    }

    // Edit tile details
    startEditing(key) {
        this.currentEditingKey = key;
        const tile = this.tiles.get(key);
        if (!tile) return;

        // Hide the action buttons
        const detailsActions = document.getElementById('detailsActions');
        if (detailsActions) {
            detailsActions.style.display = 'none';
        }

        // Set up title editing
        const titleContainer = document.getElementById('tileTitle');
        const titleValue = tile.details.title || `Tile ${key}`;
        titleContainer.innerHTML = `
            <div class="edit-field">
                <input type="text" class="edit-textarea" value="${titleValue}">
            </div>
        `;

        // Set up description editing
        const descContainer = document.getElementById('tileDescription');
        const descValue = tile.details.description || '';
        descContainer.innerHTML = `
            <div class="edit-field">
                <div id="editor"></div>
            </div>
        `;

        // Add save/cancel buttons at the bottom of the details section
        const detailsSection = document.querySelector('.details-section');
        const actionButtons = document.createElement('div');
        actionButtons.className = 'edit-actions';
        actionButtons.innerHTML = `
            <button onclick="hexGrid.saveEdit('${key}')">Save</button>
            <button onclick="hexGrid.cancelEdit('${key}')">Cancel</button>
        `;
        detailsSection.appendChild(actionButtons);

        // Initialize TinyMCE
        tinymce.init({
            target: document.getElementById('editor'),
            height: 300,
            menubar: false,
            plugins: [
                'advlist', 'autolink', 'lists', 'link', 'image', 'charmap', 'preview',
                'anchor', 'searchreplace', 'visualblocks', 'code', 'fullscreen',
                'insertdatetime', 'media', 'table', 'help', 'wordcount', 'textcolor'
            ],
            toolbar: 'undo redo | blocks | ' +
                'bold italic | forecolor backcolor | link | alignleft aligncenter ' +
                'alignright alignjustify | bullist numlist outdent indent | ' +
                'removeformat | help',
            content_style: `
                body { 
                    font-family: -apple-system, BlinkMacSystemFont, San Francisco, Segoe UI, Roboto, Helvetica Neue, sans-serif; 
                    font-size: 14px; 
                    color: #fff; 
                    margin: 0;
                    padding: 8px;
                }
                ul, ol {
                    margin: 0;
                    padding-left: 2em;
                }
                li {
                    margin: 0.25em 0;
                }
                p {
                    margin: 0.5em 0;
                }
            `,
            formats: {
                indent: { selector: 'p,h1,h2,h3,h4,h5,h6,td,th,div,ul,ol,li', styles: { marginLeft: '2em' } },
                outdent: { selector: 'p,h1,h2,h3,h4,h5,h6,td,th,div,ul,ol,li', styles: { marginLeft: '0' } }
            },
            lists_indent_on_tab: true,
            setup: (editor) => {
                editor.on('init', () => {
                    editor.setContent(descValue);
                });
            },
            promotion: false,
            branding: false,
            referrer_policy: 'origin'
        });
    }

    saveEdit(key) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        // Get title value
        const titleInput = document.querySelector('#tileTitle .edit-textarea');
        const titleValue = titleInput.value;

        // Get description value
        const editor = tinymce.get('editor');
        const descValue = editor ? editor.getContent() : '';

        // Update tile details
        if (titleValue) {
            tile.details.title = titleValue;
        }
        if (descValue) {
            tile.details.description = descValue;
        }

        // Clean up
        if (editor) {
            editor.remove();
        }

        // Show the action buttons again
        const detailsActions = document.getElementById('detailsActions');
        if (detailsActions) {
            detailsActions.style.display = 'flex';
        }

        // Remove the save/cancel buttons
        const actionButtons = document.querySelector('.edit-actions');
        if (actionButtons) {
            actionButtons.remove();
        }

        this.showTileDetails(key);
    }

    cancelEdit(key) {
        // Clean up TinyMCE
        const editor = tinymce.get('editor');
        if (editor) {
            editor.remove();
        }

        // Show the action buttons again
        const detailsActions = document.getElementById('detailsActions');
        if (detailsActions) {
            detailsActions.style.display = 'flex';
        }

        // Remove the save/cancel buttons
        const actionButtons = document.querySelector('.edit-actions');
        if (actionButtons) {
            actionButtons.remove();
        }

        this.showTileDetails(key);
    }

    // Change tile background image
    changeTileImage(key) {
        const tile = this.tiles.get(key);
        if (!tile) return;

        const input = document.createElement('input');
        input.type = 'text';
        input.id = 'imageUrl';
        input.value = tile.backgroundImage.replace(/url\(['"](.+)['"]\)/, '$1');
        input.placeholder = 'Enter image URL';
        
        const container = document.querySelector('.image-section');
        const oldButton = container.querySelector('button');
        const newButton = document.createElement('button');
        newButton.textContent = 'Save Image';
        
        oldButton.replaceWith(input);
        input.parentNode.insertBefore(newButton, input.nextSibling);
        
        newButton.onclick = () => {
            const imageUrl = input.value.trim();
            if (imageUrl) {
                tile.backgroundImage = `url("${imageUrl}")`;
                const contentSelector = this.gridType === 'hex' ? '.hex-content' : '.square-content';
                const content = tile.element.querySelector(contentSelector);
                if (content) {
                    content.style.backgroundImage = tile.backgroundImage;
                }
                this.showTileDetails(key);
            }
        };
    }

    // Remove a tile from the grid
    removeTile(q, r) {
        const key = `${q},${r}`;
        const tile = this.tiles.get(key);
        if (!tile) return;

        // Remove the tile element from the DOM
        tile.element.remove();
        // Remove the tile from our collection
        this.tiles.delete(key);
        // Hide the details panel
        this.tileDetails.classList.remove('active');
    }

    createEdgeArrows() {
        const directions = [
            { class: 'top', symbol: '↑', expand: () => this.expandBoard('top') },
            { class: 'bottom', symbol: '↓', expand: () => this.expandBoard('bottom') },
            { class: 'left', symbol: '←', expand: () => this.expandBoard('left') },
            { class: 'right', symbol: '→', expand: () => this.expandBoard('right') }
        ];

        directions.forEach(({ class: className, symbol, expand }) => {
            const arrow = document.createElement('div');
            arrow.className = `edge-arrow ${className}`;
            arrow.textContent = symbol;
            arrow.addEventListener('click', expand);
            this.gameBoard.appendChild(arrow);
        });
    }

    expandBoard(direction) {
        const expansionSize = 5; // Number of rows/columns to add
        const oldRadius = this.gridRadius;
        this.gridRadius += expansionSize;

        if (this.gridType === 'square') {
            // Create new squares in the expanded area
            for (let q = -this.gridRadius; q <= this.gridRadius; q++) {
                for (let r = -this.gridRadius; r <= this.gridRadius; r++) {
                    const key = `${q},${r}`;
                    
                    // Only create squares in the new area
                    if ((Math.abs(q) > oldRadius || Math.abs(r) > oldRadius) && !this.tiles.has(key)) {
                        this.createEmptySquare(q, r);
                    }
                }
            }
        } else {
            // Create new hexes in the expanded area
            for (let q = -this.gridRadius; q <= this.gridRadius; q++) {
                for (let r = -this.gridRadius; r <= this.gridRadius; r++) {
                    const offsetQ = q + (r % 2) * 0.5;
                    const key = `${offsetQ},${r}`;
                    
                    // Only create hexes in the new area
                    if (Math.abs(offsetQ) + Math.abs(r) <= this.gridRadius * 2 &&
                        Math.abs(offsetQ) + Math.abs(r) > oldRadius * 2) {
                        this.createEmptyHex(offsetQ, r);
                    }
                }
            }
        }

        // Adjust viewport to keep the center visible
        const viewportAdjustment = expansionSize * this.yStep;
        switch (direction) {
            case 'top':
                this.viewportY += viewportAdjustment;
                break;
            case 'bottom':
                this.viewportY -= viewportAdjustment;
                break;
            case 'left':
                this.viewportX += viewportAdjustment;
                break;
            case 'right':
                this.viewportX -= viewportAdjustment;
                break;
        }

        this.updateTilePositions();
    }

    shareBoard() {
        const boardData = this.getBoardData();

        // Include the actual CSS content directly
        const cssContent = `
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    display: flex;
    min-height: 100vh;
    background-color: #000;
    font-family: Arial, sans-serif;
    overflow: hidden;
}

.controls {
    position: fixed;
    top: 20px;
    left: 20px;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.edit-controls {
    display: none;
    gap: 10px;
}

.edit-controls.active {
    display: flex;
}

.toggle-button {
    padding: 8px 16px;
    background-color: #333;
    color: white;
    border: 2px solid #666;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
    transition: all 0.3s ease;
}

.toggle-button.edit-mode {
    background-color: #4CAF50;
    border-color: #45a049;
}

.controls button:not(.toggle-button) {
    padding: 8px 16px;
    background-color: #4CAF50;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
}

.controls button:hover {
    background-color: #45a049;
}

.game-board {
    flex: 1;
    position: relative;
    overflow: hidden;
    cursor: grab;
    background-color: #222;
    --hex-size: 50px;
    --hex-width: 86.6px;
    --hex-height: 100px;
    transition: margin-right 0.3s ease;
}

.game-board.edit-mode {
    background-color: #2a2a2a;
}

.game-board.dragging {
    cursor: grabbing;
}

.hex {
    position: absolute;
    width: var(--hex-width);
    height: var(--hex-height);
    margin: 0;
    cursor: pointer;
    transition: transform 0.2s;
}

.hex::before {
    content: '';
    position: absolute;
    width: 100%;
    height: 100%;
    background-color: #666;
    clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
    opacity: 0.4;
    transition: opacity 0.2s, background-color 0.2s;
}

.hex.filled::before {
    background-color: #0066ff;
    opacity: 1;
}

.hex::after {
    content: '';
    position: absolute;
    width: calc(100% - 8px);
    height: calc(100% - 8px);
    top: 4px;
    left: 4px;
    background-color: #000;
    clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
    opacity: 0;
    transition: opacity 0.2s;
}

.hex.filled::after {
    opacity: 1;
}

.hex-content {
    position: absolute;
    width: calc(100% - 16px);
    height: calc(100% - 16px);
    top: 8px;
    left: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1;
    background-size: contain;
    background-position: center;
    background-repeat: no-repeat;
    clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
    opacity: 0;
    transition: opacity 0.2s;
}

.hex.filled .hex-content {
    opacity: 1;
}

.game-board:not(.edit-mode) .hex:not(.filled) {
    display: none;
}

.edit-mode .hex:hover::before {
    background-color: #888;
}

/* Square Grid Styles */
.square {
    position: absolute;
    width: var(--square-size, 80px);
    height: var(--square-size, 80px);
    margin: 0;
    cursor: pointer;
    transition: transform 0.2s;
    border: 1px solid #666;
    background-color: rgba(102, 102, 102, 0.4);
    transition: background-color 0.2s, border-color 0.2s;
}

.square.filled {
    border-color: #0066ff;
    background-color: #0066ff;
}

.square-content {
    position: absolute;
    width: calc(100% - 4px);
    height: calc(100% - 4px);
    top: 2px;
    left: 2px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 2;
    background-size: contain;
    background-position: center;
    background-repeat: no-repeat;
    background-color: #000;
    opacity: 0;
    transition: opacity 0.2s;
}

.square.filled .square-content {
    opacity: 1;
}

.game-board:not(.edit-mode) .square:not(.filled) {
    display: none;
}

.edit-mode .square:hover {
    background-color: #888;
    border-color: #888;
}

.tile-details {
    position: fixed;
    right: 0;
    top: 0;
    width: 350px;
    height: 100vh;
    background: #1a1a1a;
    color: #fff;
    padding: 20px;
    transform: translateX(100%);
    transition: transform 0.3s ease, width 0.3s ease;
    z-index: 1000;
    overflow-y: auto;
}

.tile-details.expanded {
    width: 1000px;
}

.tile-details.active {
    transform: translateX(0);
}

.tile-details-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}

.tile-details-header h2 {
    margin: 0;
    font-size: 1.5em;
    color: #fff;
}

.toggle-sidebar {
    background: none;
    border: none;
    color: #fff;
    font-size: 20px;
    cursor: pointer;
    padding: 5px 10px;
    border-radius: 4px;
    transition: background-color 0.2s;
}

.tile-details.expanded .toggle-sidebar {
    transform: rotate(180deg);
}

.toggle-sidebar:hover {
    background: rgba(255, 255, 255, 0.1);
}

.game-board {
    transition: margin-right 0.3s ease;
}

.tile-details.active ~ .game-board {
    margin-right: 350px;
}

.tile-details.active.expanded ~ .game-board {
    margin-right: 600px;
}

.tile-details-content {
    display: flex;
    flex-direction: column;
    gap: 20px;
    min-height: 100%;
}

.details-section {
    background: #2a2a2a;
    padding: 15px;
    border-radius: 5px;
    flex: 1;
}

.details-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
}

.details-header h3 {
    margin: 0;
    color: #ccc;
    font-size: 1.1em;
}

.details-actions {
    display: flex;
    gap: 8px;
}

.edit-link {
    background: none;
    border: none;
    color: #4CAF50;
    cursor: pointer;
    font-size: 0.9em;
    padding: 4px 8px;
    border-radius: 4px;
    transition: background-color 0.2s;
}

.reset-link {
    background: none;
    border: none;
    color: #f44336;
    cursor: pointer;
    font-size: 0.9em;
    padding: 4px 8px;
    border-radius: 4px;
    transition: background-color 0.2s;
}

.edit-link:hover {
    background: rgba(76, 175, 80, 0.1);
}

.reset-link:hover {
    background: rgba(244, 67, 54, 0.1);
}

.details-field {
    display: flex;
    flex-direction: column;
    gap: 5px;
}

.details-label {
    color: #888;
    font-size: 0.9em;
}

.details-value {
    padding: 8px;
    background: #333;
    border-radius: 4px;
    min-height: 20px;
    word-break: break-word;
    line-height: 1.4;
}

.details-value ul, .details-value ol {
    list-style-type: disc;
    padding-left: 2em;
    margin: 0.5em 0;
}

.details-value li {
    margin: 0.25em 0;
}

.details-value a {
    color: #4CAF50;
    text-decoration: none;
}

.details-value a:hover {
    text-decoration: underline;
}

.image-section {
    margin-top: auto;
    padding: 15px;
    background: #2a2a2a;
    border-radius: 5px;
}

.image-section h3 {
    color: #ccc;
    margin-bottom: 10px;
    font-size: 1.1em;
}

.image-preview {
    margin-bottom: 10px;
    text-align: center;
}

.image-preview img {
    max-width: 100%;
    max-height: 150px;
    border-radius: 4px;
}

/* Override styles for view-only mode */
.controls { display: none !important; }
.edit-controls { display: none !important; }
.toggle-button { display: none !important; }
.game-board { cursor: default; }
.hex { cursor: pointer; }
.hex:hover::before { background-color: inherit !important; }
.square { cursor: pointer; }
.square:hover { background-color: inherit !important; border-color: inherit !important; }
`;

        // Create the HTML content
        const htmlContent = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${boardData.gridType === 'square' ? 'Square' : 'Hexagonal'} Game Board - View</title>
    <style>
        ${cssContent}
    </style>
</head>
<body>
    <div class="game-board" id="gameBoard">
        <!-- Game tiles will be added here dynamically -->
    </div>
    <div id="tileDetails" class="tile-details">
        <div class="tile-details-header">
            <h2>Tile Details</h2>
            <button id="toggleSidebar" class="toggle-sidebar">◀</button>
        </div>
        <div id="tileContent"></div>
    </div>
    <script>
        // Include the HexGrid class
        class HexGrid {
            constructor() {
                this.gameBoard = document.getElementById('gameBoard');
                this.tileDetails = document.getElementById('tileDetails');
                this.tileContent = document.getElementById('tileContent');
                this.tiles = new Map();
                this.contextMenu = null;

                // Size calculations for perfect hexagon tiling
                this.hexSize = 50;
                this.hexWidth = this.hexSize * Math.sqrt(3);
                this.hexHeight = this.hexSize * 2;
                this.hexSpacing = 5;
                
                // Calculate offsets based on hexagon geometry
                this.xStep = this.hexWidth + this.hexSpacing;
                this.yStep = (this.hexHeight * 3/4) + (this.hexSpacing * Math.cos(Math.PI/6));
                
                // Grid dimensions
                this.gridRadius = 10;
                
                // Viewport position and zoom
                this.viewportX = window.innerWidth / 2;
                this.viewportY = window.innerHeight / 2;
                this.zoom = 1;
                this.isDragging = false;
                this.dragStart = { x: 0, y: 0 };
                
                // Edit mode state
                this.isEditMode = false;
                
                // Initialize the grid
                this.initializeGrid();
                
                // Add event listeners
                this.gameBoard.addEventListener('click', this.handleBoardClick.bind(this));
                this.setupDragHandlers();
                this.setupZoomHandlers();
            }

            initializeGrid() {
                this.gameBoard.innerHTML = '';
                this.tiles.clear();

                if (this.gridType === 'square') {
                    // Create a square grid
                    for (let q = -this.gridRadius; q <= this.gridRadius; q++) {
                        for (let r = -this.gridRadius; r <= this.gridRadius; r++) {
                            this.createEmptySquare(q, r);
                        }
                    }
                } else {
                    // Create a hexagonal grid with offset rows
                    for (let q = -this.gridRadius; q <= this.gridRadius; q++) {
                        for (let r = -this.gridRadius; r <= this.gridRadius; r++) {
                            const offsetQ = q + (r % 2) * 0.5;
                            if (Math.abs(offsetQ) + Math.abs(r) <= this.gridRadius * 2) {
                                this.createEmptyHex(offsetQ, r);
                            }
                        }
                    }
                }
            }

            createEmptySquare(q, r) {
                const key = \`\${q},\${r}\`;
                const { x, y } = this.gridToPixel(q, r);
                
                const square = document.createElement('div');
                square.className = 'square';
                square.style.left = \`\${x}px\`;
                square.style.top = \`\${y}px\`;

                const content = document.createElement('div');
                content.className = 'square-content';
                content.style.backgroundImage = 'url("https://via.placeholder.com/80x80")';
                square.appendChild(content);

                const tileData = {
                    element: square,
                    q,
                    r,
                    backgroundImage: content.style.backgroundImage,
                    details: {
                        name: \`Tile \${key}\`,
                        description: 'Click to view details'
                    }
                };

                this.tiles.set(key, tileData);
                this.gameBoard.appendChild(square);
            }

            createEmptyHex(q, r) {
                const key = \`\${q},\${r}\`;
                const { x, y } = this.gridToPixel(q, r);
                
                const hex = document.createElement('div');
                hex.className = 'hex';
                hex.style.left = \`\${x}px\`;
                hex.style.top = \`\${y}px\`;

                const content = document.createElement('div');
                content.className = 'hex-content';
                content.style.backgroundImage = 'url("https://via.placeholder.com/100x115")';
                hex.appendChild(content);

                const tileData = {
                    element: hex,
                    q,
                    r,
                    backgroundImage: content.style.backgroundImage,
                    details: {
                        name: \`Tile \${key}\`,
                        description: 'Click to view details'
                    }
                };

                this.tiles.set(key, tileData);
                this.gameBoard.appendChild(hex);
            }

            gridToPixel(q, r) {
                if (this.gridType === 'square') {
                    const x = q * this.xStep;
                    const y = r * this.yStep;
                    return { 
                        x: x + this.viewportX, 
                        y: y + this.viewportY 
                    };
                } else {
                    const x = q * this.xStep;
                    const y = -r * this.yStep;
                    return { 
                        x: x + this.viewportX, 
                        y: y + this.viewportY 
                    };
                }
            }

            updateTilePositions() {
                this.tiles.forEach((tile, key) => {
                    const { x, y } = this.gridToPixel(tile.q, tile.r);
                    tile.element.style.left = \`\${x}px\`;
                    tile.element.style.top = \`\${y}px\`;
                });
            }

            setupDragHandlers() {
                let isDragging = false;
                let dragStart = { x: 0, y: 0 };

                this.gameBoard.addEventListener('mousedown', (e) => {
                    if (e.button !== 0) return;

                    isDragging = false;
                    dragStart = {
                        x: e.clientX - this.viewportX,
                        y: e.clientY - this.viewportY
                    };

                    const handleMouseMove = (e) => {
                        const dx = e.clientX - (dragStart.x + this.viewportX);
                        const dy = e.clientY - (dragStart.y + this.viewportY);
                        const distance = Math.sqrt(dx * dx + dy * dy);

                        if (distance > 5) {
                            isDragging = true;
                            this.gameBoard.classList.add('dragging');
                        }

                        if (isDragging) {
                            this.viewportX = e.clientX - dragStart.x;
                            this.viewportY = e.clientY - dragStart.y;
                            this.updateTilePositions();
                        }
                    };

                    const handleMouseUp = (e) => {
                        window.removeEventListener('mousemove', handleMouseMove);
                        window.removeEventListener('mouseup', handleMouseUp);
                        
                        if (isDragging) {
                            e.preventDefault();
                            e.stopPropagation();
                        }
                        
                        isDragging = false;
                        this.gameBoard.classList.remove('dragging');
                    };

                    window.addEventListener('mousemove', handleMouseMove);
                    window.addEventListener('mouseup', handleMouseUp);
                });
            }

            setupZoomHandlers() {
                this.gameBoard.addEventListener('wheel', (e) => {
                    e.preventDefault();
                    const zoomFactor = 1.1;
                    const delta = e.deltaY > 0 ? 1/zoomFactor : zoomFactor;
                    this.setZoom(this.zoom * delta);
                });
            }

            setZoom(newZoom) {
                this.zoom = Math.max(0.5, Math.min(2, newZoom));
                
                if (this.gridType === 'square') {
                    // Update square sizes while keeping spacing consistent
                    const baseSize = 80;
                    this.squareSize = baseSize * this.zoom;
                    this.xStep = this.squareSize + this.squareSpacing;
                    this.yStep = this.squareSize + this.squareSpacing;

                    // Update CSS variables for square sizing
                    this.gameBoard.style.setProperty('--square-size', \`\${this.squareSize}px\`);
                } else {
                    // Update hex sizes while keeping spacing consistent
                    const baseSize = 50;
                    this.hexSize = baseSize * this.zoom;
                    this.hexWidth = this.hexSize * Math.sqrt(3);
                    this.hexHeight = this.hexSize * 2;
                    this.xStep = this.hexWidth + this.hexSpacing;
                    this.yStep = (this.hexHeight * 3/4) + (this.hexSpacing * Math.cos(Math.PI/6));

                    // Update CSS variables for hex sizing
                    this.gameBoard.style.setProperty('--hex-size', \`\${this.hexSize}px\`);
                    this.gameBoard.style.setProperty('--hex-width', \`\${this.hexWidth}px\`);
                    this.gameBoard.style.setProperty('--hex-height', \`\${this.hexHeight}px\`);
                }
                
                this.updateTilePositions();
            }

            handleBoardClick(e) {
                if (e.target === this.gameBoard) {
                    this.tileDetails.classList.remove('active');
                } else {
                    // Check for both hex and square tiles
                    const tile = e.target.closest('.hex') || e.target.closest('.square');
                    if (tile) {
                        const key = Array.from(this.tiles.keys()).find(k => this.tiles.get(k).element === tile);
                        if (key) {
                            this.showTileDetails(key);
                        }
                    }
                }
            }

            showTileDetails(key) {
                const tile = this.tiles.get(key);
                if (!tile) return;

                let content = \`
                    <div class="tile-details-content">
                        <div class="details-section">
                            <div class="details-field">
                                <div class="details-value">
                                    \${tile.details.description}
                                </div>
                            </div>
                        </div>
                        <div class="image-section">
                            <div class="image-preview">
                                <img src="\${tile.backgroundImage.replace(/url\\(['"](.+)['"]\\)/, '$1')}" alt="Tile preview">
                            </div>
                        </div>
                    </div>
                \`;

                this.tileContent.innerHTML = content;
                this.tileDetails.classList.add('active');

                // Update the sidebar header with the tile title (matching view mode behavior)
                const headerTitle = this.tileDetails.querySelector('.tile-details-header h2');
                if (headerTitle) {
                    headerTitle.textContent = tile.details.title || \`Tile \${key}\`;
                }
            }

            updateEditModeUI() {
                this.gameBoard.classList.toggle('edit-mode', this.isEditMode);
            }

            loadBoardData(boardData) {
                this.initializeGrid();
                
                this.viewportX = boardData.viewportX || window.innerWidth / 2;
                this.viewportY = boardData.viewportY || window.innerHeight / 2;
                this.zoom = boardData.zoom || 1;
                
                boardData.tiles.forEach(tileData => {
                    const { q, r, backgroundImage, details } = tileData;
                    const key = \`\${q},\${r}\`;
                    const tile = this.tiles.get(key);
                    if (tile) {
                        tile.element.classList.add('filled');
                        tile.backgroundImage = backgroundImage;
                        tile.details = details;
                        tile.element.querySelector('.hex-content').style.backgroundImage = backgroundImage;
                    }
                });

                this.updateTilePositions();
            }
        }

        // Override the HexGrid class to disable editing features
        class ViewOnlyHexGrid extends HexGrid {
            constructor() {
                super();
                // Force view mode
                this.isEditMode = false;
                this.updateEditModeUI();
                
                // Add sidebar toggle listener
                document.getElementById('toggleSidebar').addEventListener('click', () => this.toggleSidebar());
                
                // Load the board state
                this.loadBoardData(${JSON.stringify(boardData)});
            }

            loadBoardData(boardData) {
                // Set grid type first
                this.gridType = boardData.gridType || 'hex';
                
                // Update grid size calculations based on type
                if (this.gridType === 'square') {
                    this.squareSize = 80;
                    this.squareSpacing = 5;
                    this.xStep = this.squareSize + this.squareSpacing;
                    this.yStep = this.squareSize + this.squareSpacing;
                } else {
                    this.hexSize = 50;
                    this.hexWidth = this.hexSize * Math.sqrt(3);
                    this.hexHeight = this.hexSize * 2;
                    this.hexSpacing = 5;
                    this.xStep = this.hexWidth + this.hexSpacing;
                    this.yStep = (this.hexHeight * 3/4) + (this.hexSpacing * Math.cos(Math.PI/6));
                }
                
                // Initialize empty grid first
                this.initializeGrid();
                
                this.viewportX = boardData.viewportX || window.innerWidth / 2;
                this.viewportY = boardData.viewportY || window.innerHeight / 2;
                this.zoom = boardData.zoom || 1;
                
                // Fill and update tiles
                boardData.tiles.forEach(tileData => {
                    const { q, r, backgroundImage, details } = tileData;
                    const key = \`\${q},\${r}\`;
                    const tile = this.tiles.get(key);
                    if (tile) {
                        tile.element.classList.add('filled');
                        tile.backgroundImage = backgroundImage;
                        tile.details = details;
                        const contentSelector = this.gridType === 'hex' ? '.hex-content' : '.square-content';
                        const content = tile.element.querySelector(contentSelector);
                        if (content) {
                            content.style.backgroundImage = backgroundImage;
                        }
                    }
                });

                this.updateTilePositions();
            }
            
            toggleSidebar() {
                this.tileDetails.classList.toggle('expanded');
            }

            // Override methods to disable editing
            toggleTile() { return; }
            showContextMenu() { return; }
            startEditing() { return; }
            saveEdit() { return; }
            cancelEdit() { return; }
            changeTileImage() { return; }
            removeTile() { return; }
            expandBoard() { return; }
        }

        // Initialize the view-only grid
        const hexGrid = new ViewOnlyHexGrid();
    </script>
</body>
</html>`;

        // Create a blob and download link
        const blob = new Blob([htmlContent], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${boardData.gridType}-board-view.html`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    toggleSidebar() {
        this.tileDetails.classList.toggle('expanded');
        // If there's an active editor, reinitialize it to adjust to new width
        const editor = tinymce.get('editor');
        if (editor) {
            editor.remove();
            this.startEditing(this.currentEditingKey);
        }
    }
}

// Initialize the game board (supports both hex and square grids)
const hexGrid = new HexGrid(); 
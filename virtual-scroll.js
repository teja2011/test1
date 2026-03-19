/**
 * VirtualScroll - виртуальный скроллинг для эффективного рендеринга больших списков
 * Рендерит только видимые элементы + буфер
 */
(function(global) {
    'use strict';

    function VirtualScroll(container, options) {
        this.container = typeof container === 'string' 
            ? document.querySelector(container) 
            : container;
        
        if (!this.container) {
            console.error('[VirtualScroll] Container not found');
            return;
        }

        this.options = Object.assign({
            itemHeight: 60,      // Средняя высота элемента в px
            overscan: 5,         // Буфер элементов сверху/снизу
            renderItem: null,    // Функция рендеринга элемента
            onScroll: null,      // Callback при скролле
            loadMore: null       // Функция подгрузки данных
        }, options);

        this.items = [];
        this.scrollTop = 0;
        this.containerHeight = 0;
        this.startIndex = 0;
        this.endIndex = 0;
        this.isScrolling = false;
        this.scrollTimeout = null;
        this.pendingScroll = null;

        this.init();
    }

    VirtualScroll.prototype.init = function() {
        // Создаем структуру для виртуализации
        this.container.style.overflow = 'auto';
        this.container.style.position = 'relative';
        
        // Spacer для установки общей высоты
        this.spacer = document.createElement('div');
        this.spacer.style.position = 'absolute';
        this.spacer.style.left = '0';
        this.spacer.style.right = '0';
        this.spacer.style.top = '0';
        this.spacer.style.pointerEvents = 'none';
        this.container.appendChild(this.spacer);

        // Контейнер для видимых элементов
        this.viewport = document.createElement('div');
        this.viewport.style.position = 'sticky';
        this.viewport.style.top = '0';
        this.viewport.style.left = '0';
        this.viewport.style.right = '0';
        this.viewport.style.pointerEvents = 'none';
        this.container.appendChild(this.viewport);

        // Обработчик скролла с throttle
        this.boundScrollHandler = this.onScroll.bind(this);
        this.container.addEventListener('scroll', this.boundScrollHandler, { passive: true });

        // Обработчик изменения размера
        this.boundResizeHandler = this.onResize.bind(this);
        if (typeof ResizeObserver !== 'undefined') {
            this.resizeObserver = new ResizeObserver(this.boundResizeHandler);
            this.resizeObserver.observe(this.container);
        } else {
            window.addEventListener('resize', this.boundResizeHandler);
        }

        this.updateContainerHeight();
    };

    VirtualScroll.prototype.updateContainerHeight = function() {
        this.containerHeight = this.container.clientHeight;
    };

    VirtualScroll.prototype.setItems = function(items) {
        this.items = items || [];
        this.updateSpacer();
        this.render();
    };

    VirtualScroll.prototype.updateSpacer = function() {
        const totalHeight = this.items.length * this.options.itemHeight;
        this.spacer.style.height = totalHeight + 'px';
    };

    VirtualScroll.prototype.onScroll = function() {
        var self = this;
        this.scrollTop = this.container.scrollTop;

        // Throttle рендеринга
        if (!this.isScrolling) {
            this.isScrolling = true;
            if (this.options.onScroll) {
                this.options.onScroll(this.scrollTop);
            }
        }

        clearTimeout(this.scrollTimeout);
        this.scrollTimeout = setTimeout(function() {
            self.isScrolling = false;
            self.render();
        }, 16); // ~60fps

        // Проверка загрузки ещё данных
        this.checkLoadMore();
    };

    VirtualScroll.prototype.checkLoadMore = function() {
        if (!this.options.loadMore) return;

        const scrollBottom = this.scrollTop + this.containerHeight;
        const totalHeight = this.items.length * this.options.itemHeight;
        
        // Если доскроллили до конца (с запасом 200px)
        if (totalHeight - scrollBottom < 200) {
            this.options.loadMore();
        }
    };

    VirtualScroll.prototype.onResize = function() {
        this.updateContainerHeight();
        this.render();
    };

    VirtualScroll.prototype.render = function() {
        if (!this.items.length) {
            this.viewport.innerHTML = '';
            return;
        }

        const itemHeight = this.options.itemHeight;
        const overscan = this.options.overscan;
        
        // Вычисляем видимый диапазон
        this.startIndex = Math.max(0, Math.floor(this.scrollTop / itemHeight) - overscan);
        this.endIndex = Math.min(
            this.items.length,
            Math.ceil((this.scrollTop + this.containerHeight) / itemHeight) + overscan
        );

        // Очищаем и рендерим только видимые элементы
        this.viewport.innerHTML = '';
        this.viewport.style.transform = 'translateY(' + (this.startIndex * itemHeight) + 'px)';

        const fragment = document.createDocumentFragment();
        
        for (let i = this.startIndex; i < this.endIndex; i++) {
            const item = this.items[i];
            const el = this.createItemElement(item, i);
            if (el) {
                fragment.appendChild(el);
            }
        }

        this.viewport.appendChild(fragment);

        // Сохраняем позицию скролла
        if (this.pendingScroll !== null) {
            this.container.scrollTop = this.pendingScroll;
            this.pendingScroll = null;
        }
    };

    VirtualScroll.prototype.createItemElement = function(item, index) {
        if (typeof this.options.renderItem !== 'function') {
            return null;
        }

        const el = this.options.renderItem(item, index);
        if (!el) return null;

        // Устанавливаем высоту и позиционирование
        el.style.height = this.options.itemHeight + 'px';
        el.style.position = 'relative';
        el.style.pointerEvents = 'auto';
        
        return el;
    };

    VirtualScroll.prototype.scrollTo = function(index) {
        const targetScroll = index * this.options.itemHeight;
        this.pendingScroll = targetScroll;
        this.container.scrollTop = targetScroll;
        this.render();
    };

    VirtualScroll.prototype.scrollToBottom = function() {
        const maxScroll = this.items.length * this.options.itemHeight - this.containerHeight;
        this.pendingScroll = Math.max(0, maxScroll);
        this.container.scrollTop = this.pendingScroll;
        this.render();
    };

    VirtualScroll.prototype.destroy = function() {
        this.container.removeEventListener('scroll', this.boundScrollHandler);
        
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
        } else {
            window.removeEventListener('resize', this.boundResizeHandler);
        }

        if (this.spacer && this.spacer.parentNode) {
            this.spacer.parentNode.removeChild(this.spacer);
        }
        if (this.viewport && this.viewport.parentNode) {
            this.viewport.parentNode.removeChild(this.viewport);
        }
    };

    // Экспорт
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = VirtualScroll;
    } else {
        global.VirtualScroll = VirtualScroll;
    }

})(typeof window !== 'undefined' ? window : this);

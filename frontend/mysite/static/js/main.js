// 收藏功能
document.addEventListener('DOMContentLoaded', function () {
    // 收藏按钮点击事件
    const favoriteBtns = document.querySelectorAll('.favorite-btn');

    favoriteBtns.forEach(btn => {
        btn.addEventListener('click', function () {
            const announcementId = this.dataset.id;

            // 这里应该发送AJAX请求到后端
            // 暂时只是前端交互演示
            if (this.textContent === '收藏') {
                this.textContent = '已收藏';
                this.style.background = '#c8232c';
                this.style.color = '#fff';
            } else {
                this.textContent = '收藏';
                this.style.background = '#fff';
                this.style.color = '#c8232c';
            }
        });
    });
});
